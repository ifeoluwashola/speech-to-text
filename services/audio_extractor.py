import os
import re
import shutil
import logging
from typing import Optional, Tuple, Dict, Any
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import yt_dlp

logger = logging.getLogger("audio_extractor")
logger.setLevel(logging.INFO)


def extract_youtube_video_id(url: str) -> Optional[str]:
    """
    Extract standard 11-character YouTube video ID from various URL patterns:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    - https://www.youtube.com/v/VIDEO_ID
    - https://www.youtube.com/shorts/VIDEO_ID
    """
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})',
        r'(?:embed\/)([0-9A-Za-z_-]{11})',
        r'(?:shorts\/)([0-9A-Za-z_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def parse_timestamp(val: Optional[str]) -> Optional[float]:
    """
    Parse a user timestamp string into total seconds.
    Supports formats:
    - 'HH:MM:SS' (e.g. '01:15:30' -> 4530.0)
    - 'MM:SS' (e.g. '35:00' -> 2100.0)
    - 'SS' (e.g. '450' -> 450.0)
    Returns None if empty or not provided.
    """
    if not val or not str(val).strip():
        return None
    val = str(val).strip()
    parts = val.split(':')
    try:
        if len(parts) == 1:
            return max(0.0, float(parts[0]))
        elif len(parts) == 2:
            return max(0.0, float(parts[0]) * 60.0 + float(parts[1]))
        elif len(parts) == 3:
            return max(0.0, float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2]))
    except (ValueError, TypeError):
        raise ValueError(f"Invalid timestamp format '{val}'. Please use MM:SS or HH:MM:SS (e.g. 35:00 or 01:15:00).")
    raise ValueError(f"Invalid timestamp format '{val}'. Please use MM:SS or HH:MM:SS (e.g. 35:00 or 01:15:00).")


def format_transcript_snippets(snippets: list) -> str:
    """
    Format raw transcript snippets into natural, readable, continuous paragraphs.
    Avoids choppy line-by-line subtitle cuts while preserving verbatim text.
    """
    if not snippets:
        return ""
    
    paragraphs = []
    current_sentences = []
    
    for item in snippets:
        if isinstance(item, dict):
            text = item.get("text", "")
        else:
            text = getattr(item, "text", "")
            
        text = text.strip()
        # Remove music tags like [Music], [♪♪♪], ♪, or (Music)
        clean_text = re.sub(r'\[[Mm]usic\]|\([Mm]usic\)|\[\s*♪+[\s♪]*\]|♪+', '', text).strip()
        if not clean_text:
            continue
            
        current_sentences.append(clean_text)
        
        # Start a new paragraph roughly every 4-6 sentences or after pause
        if len(current_sentences) >= 5 or clean_text.endswith(('.', '!', '?')):
            if len(current_sentences) >= 4:
                paragraphs.append(" ".join(current_sentences))
                current_sentences = []
                
    if current_sentences:
        paragraphs.append(" ".join(current_sentences))
        
    return "\n\n".join(paragraphs)


def try_fetch_youtube_captions(
    video_id: str,
    start_seconds: Optional[float] = None,
    end_seconds: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """
    Attempt to fetch human or auto-generated English captions directly from YouTube.
    If start_seconds and/or end_seconds are provided, filters snippets to that exact window.
    Returns dict with text and duration if successful, else None.
    """
    try:
        api = YouTubeTranscriptApi()
        data = None
        try:
            data = api.fetch(video_id, languages=('en', 'en-US', 'en-GB'))
        except Exception:
            try:
                transcript_list = api.list(video_id)
                for t in transcript_list:
                    if t.language_code.startswith('en'):
                        data = t.fetch()
                        break
                if not data:
                    for t in transcript_list:
                        if t.is_translatable:
                            data = t.translate('en').fetch()
                            break
            except Exception:
                pass
                
        if data:
            all_snippets = list(data)
            if not all_snippets:
                return None
                
            # Filter snippets if time-range specified
            filtered_snippets = []
            for s in all_snippets:
                s_start = s.start if hasattr(s, 'start') else s.get("start", 0.0)
                s_dur = s.duration if hasattr(s, 'duration') else s.get("duration", 0.0)
                s_end = s_start + s_dur
                
                # Check overlap with [start_seconds, end_seconds]
                if start_seconds is not None and s_end < start_seconds:
                    continue
                if end_seconds is not None and s_start > end_seconds:
                    continue
                filtered_snippets.append(s)
                
            if not filtered_snippets:
                return None
                
            # Calculate duration of the filtered range
            first_snippet = filtered_snippets[0]
            last_snippet = filtered_snippets[-1]
            first_start = first_snippet.start if hasattr(first_snippet, 'start') else first_snippet.get("start", 0.0)
            last_end = (last_snippet.start if hasattr(last_snippet, 'start') else last_snippet.get("start", 0.0)) + \
                       (last_snippet.duration if hasattr(last_snippet, 'duration') else last_snippet.get("duration", 0.0))
            
            calc_duration = max(0.0, last_end - first_start)
            formatted_text = format_transcript_snippets(filtered_snippets)
            
            if formatted_text.strip():
                return {
                    "source": "youtube_caption",
                    "text": formatted_text,
                    "duration_seconds": round(calc_duration, 1),
                    "is_instant": True,
                    "range_applied": (start_seconds is not None or end_seconds is not None)
                }
    except Exception as e:
        logger.warning(f"Error checking YouTube transcript API: {e}")
        
    return None


def download_youtube_audio(
    url: str,
    output_dir: str,
    start_seconds: Optional[float] = None,
    end_seconds: Optional[float] = None
) -> str:
    """
    Download only the audio stream of a YouTube video into output_dir.
    If start_seconds or end_seconds is specified and ffmpeg is available,
    downloads ONLY the requested section (cutting down download time significantly).
    """
    output_template = os.path.join(output_dir, "%(id)s.%(ext)s")
    has_ffmpeg = shutil.which("ffmpeg") is not None
    
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
    }
    
    # If time slicing is requested and ffmpeg is available, download sections
    if (start_seconds is not None or end_seconds is not None) and has_ffmpeg:
        s_start = start_seconds if start_seconds is not None else 0.0
        s_end = end_seconds if end_seconds is not None else float('inf')
        ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(None, [(s_start, s_end)])
        ydl_opts['force_keyframes_at_cuts'] = True
    
    if has_ffmpeg:
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }]
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_id = info.get('id', 'audio')
        
    # Find the downloaded audio file in output_dir
    for file in os.listdir(output_dir):
        if file.startswith(video_id) and not file.endswith(('.part', '.ytdl')):
            return os.path.join(output_dir, file)
            
    # Fallback to any audio file in temp dir
    for file in os.listdir(output_dir):
        if not file.endswith(('.part', '.ytdl')):
            return os.path.join(output_dir, file)
            
    raise FileNotFoundError("Audio extraction failed; no output audio file found.")


async def save_upload_to_file(upload_file, target_path: str, chunk_size: int = 1024 * 1024) -> None:
    """
    Stream an uploaded audio file (which may be 500MB+ for 2-hour tapes)
    to target_path on disk in chunks, keeping RAM usage low.
    """
    with open(target_path, "wb") as f:
        while True:
            chunk = await upload_file.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
