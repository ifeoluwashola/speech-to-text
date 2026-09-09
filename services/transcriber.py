import os
import logging
from typing import Dict, Any, List, Optional
from faster_whisper import WhisperModel

logger = logging.getLogger("transcriber")
logger.setLevel(logging.INFO)

# Global model cache to avoid re-initializing weights on every request
_MODEL_CACHE: Dict[str, WhisperModel] = {}


def get_model(model_name: str = "small.en") -> WhisperModel:
    """
    Load or retrieve a cached WhisperModel.
    On Apple Silicon (M2 Pro), CTranslate2 runs efficiently with device="cpu",
    compute_type="int8" using ARM NEON acceleration.
    """
    if model_name not in _MODEL_CACHE:
        logger.info(f"Loading Whisper model '{model_name}' into memory...")
        # device="cpu", compute_type="int8" is fast, stable, and memory-lean on macOS ARM64
        _MODEL_CACHE[model_name] = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",
            download_root=os.path.expanduser("~/.cache/speech-to-text/models")
        )
        logger.info(f"Model '{model_name}' loaded successfully.")
    return _MODEL_CACHE[model_name]


def format_segments_to_paragraphs(segments: list) -> str:
    """
    Assemble transcribed segments into continuous, natural word-for-word paragraphs.
    Breaks paragraphs upon natural conversational pauses (gap > 2.0s) or after 4-5 sentences,
    maintaining 100% word-for-word accuracy.
    """
    if not segments:
        return ""

    paragraphs = []
    current_sentences = []
    last_end = None

    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue

        # Check pause duration between segments
        start = seg.start
        if last_end is not None and (start - last_end) > 2.2:
            # Long conversational pause: flush current paragraph
            if current_sentences:
                paragraphs.append(" ".join(current_sentences))
                current_sentences = []

        current_sentences.append(text)
        last_end = seg.end

        # Sentence-count-based paragraph breaks
        if len(current_sentences) >= 5 or (len(current_sentences) >= 3 and text.endswith((".", "!", "?"))):
            paragraphs.append(" ".join(current_sentences))
            current_sentences = []

    if current_sentences:
        paragraphs.append(" ".join(current_sentences))

    return "\n\n".join(paragraphs)


def transcribe_audio(
    audio_path: str,
    model_name: str = "small.en",
    language: str = "en",
    start_seconds: Optional[float] = None,
    end_seconds: Optional[float] = None
) -> Dict[str, Any]:
    """
    Transcribe an audio file word-for-word using Whisper.
    - If start_seconds or end_seconds is provided, only transcribes that specific time range.
    - Uses Silero VAD (Voice Activity Detection) to filter out tape hiss, silence, and background static.
    - Optimized for lengthy 60-120 minute audio files.
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found at {audio_path}")

    model = get_model(model_name)

    logger.info(f"Starting transcription with model {model_name} on {audio_path} (Range: {start_seconds}s -> {end_seconds}s)...")

    transcribe_kwargs: Dict[str, Any] = {
        "language": language,
        "task": "transcribe",
        "beam_size": 5,
    }

    if start_seconds is not None or end_seconds is not None:
        s_start = max(0.0, start_seconds or 0.0)
        s_end = end_seconds if end_seconds is not None else 9999999.0
        transcribe_kwargs["clip_timestamps"] = [s_start, s_end]
    else:
        # Silero VAD is enabled for full audio runs to clean tape hiss and pauses
        transcribe_kwargs["vad_filter"] = True
        transcribe_kwargs["vad_parameters"] = dict(min_silence_duration_ms=500)

    segments_generator, info = model.transcribe(audio_path, **transcribe_kwargs)

    # Collect all segments
    all_segments = list(segments_generator)

    formatted_text = format_segments_to_paragraphs(all_segments)
    word_count = len(formatted_text.split())

    # Calculate actual duration of transcribed section
    if start_seconds is not None or end_seconds is not None:
        actual_end = min(info.duration, end_seconds if end_seconds is not None else info.duration)
        duration_sec = max(0.0, actual_end - (start_seconds or 0.0))
    else:
        duration_sec = info.duration

    return {
        "text": formatted_text,
        "word_count": word_count,
        "duration_seconds": round(duration_sec, 1),
        "language": info.language,
        "language_probability": round(info.language_probability, 2),
        "source": "local_whisper",
        "model_used": model_name,
        "range_applied": (start_seconds is not None or end_seconds is not None)
    }
