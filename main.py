import os
import time
import shutil
import tempfile
import logging
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from services.audio_extractor import (
    extract_youtube_video_id,
    try_fetch_youtube_captions,
    download_youtube_audio,
    save_upload_to_file
)
from services.transcriber import transcribe_audio, get_model

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("speech_to_text_app")

app = FastAPI(
    title="Ephemeral Speech-to-Text System",
    description="Word-for-word audio & YouTube transcription with zero persistent media storage.",
    version="1.0.0"
)

# Enable CORS for local use
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class YouTubeRequest(BaseModel):
    url: str
    model: Optional[str] = "small.en"
    start_time: Optional[str] = None
    end_time: Optional[str] = None


@app.get("/api/system-status")
async def system_status():
    """Returns available models and system readiness."""
    return {
        "status": "ready",
        "default_model": "small.en",
        "available_models": [
            {"id": "base.en", "name": "Base (Fastest, ~140MB)", "desc": "Great for quick clear audio"},
            {"id": "small.en", "name": "Small (Recommended, ~460MB)", "desc": "Best balance of speed & high accuracy"},
            {"id": "medium.en", "name": "Medium (High Detail, ~1.5GB)", "desc": "Highest accuracy for muffled/noisy tapes"}
        ],
        "zero_retention_policy": "Enforced. No audio, video, or links are permanently stored."
    }


@app.post("/api/transcribe-youtube")
async def transcribe_youtube(req: YouTubeRequest):
    """
    Transcribe a YouTube video (or a specific section):
    1. First checks for human or auto-generated English captions (instant result in ~1-2s).
       If start_time/end_time are provided, only returns the requested portion.
    2. If no captions, downloads the audio stream (or section) and runs Whisper.
    3. Guarantees immediate deletion of all temporary media in a `finally` block.
    """
    from services.audio_extractor import parse_timestamp

    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="YouTube URL is required.")

    video_id = extract_youtube_video_id(url)
    if not video_id:
        raise HTTPException(
            status_code=400,
            detail="Invalid YouTube URL. Please provide a valid YouTube watch, short, or youtu.be link."
        )

    # Parse and validate time range
    try:
        start_seconds = parse_timestamp(req.start_time)
        end_seconds = parse_timestamp(req.end_time)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    if start_seconds is not None and end_seconds is not None and start_seconds >= end_seconds:
        raise HTTPException(status_code=400, detail="Start time must be earlier than End time.")

    start_time_proc = time.time()
    logger.info(f"Received YouTube request for video ID: {video_id} (Section: {start_seconds}s -> {end_seconds}s)")

    # --- FAST PATH: Check existing captions ---
    caption_result = try_fetch_youtube_captions(video_id, start_seconds=start_seconds, end_seconds=end_seconds)
    if caption_result and caption_result.get("text"):
        elapsed = round(time.time() - start_time_proc, 2)
        text = caption_result["text"]
        logger.info(f"Instant caption found for {video_id} in {elapsed}s")
        range_msg = f" (Section: {req.start_time or '00:00'} to {req.end_time or 'end'})" if (start_seconds or end_seconds) else ""
        return {
            "success": True,
            "text": text,
            "word_count": len(text.split()),
            "duration_seconds": round(caption_result.get("duration_seconds", 0), 1),
            "source": "youtube_captions",
            "is_instant": True,
            "processing_time_seconds": elapsed,
            "range_applied": caption_result.get("range_applied", False),
            "message": f"Transcribed instantly from YouTube English captions{range_msg}."
        }

    # --- FALLBACK PATH: Download audio stream and transcribe locally ---
    temp_dir = tempfile.mkdtemp(prefix="stt_yt_")
    try:
        logger.info(f"No direct captions available. Downloading audio section to temp path: {temp_dir}")
        audio_file_path = download_youtube_audio(url, temp_dir, start_seconds=start_seconds, end_seconds=end_seconds)

        model_name = req.model if req.model else "small.en"
        # If ffmpeg cut the section during download, start_seconds is already at 0 in the cut file
        # But if yt-dlp downloaded the whole stream, clip_timestamps slices it in Whisper
        has_cut_during_download = shutil.which("ffmpeg") is not None and (start_seconds is not None or end_seconds is not None)
        whisper_start = None if has_cut_during_download else start_seconds
        whisper_end = None if has_cut_during_download else end_seconds

        result = transcribe_audio(
            audio_file_path,
            model_name=model_name,
            language="en",
            start_seconds=whisper_start,
            end_seconds=whisper_end
        )
        elapsed = round(time.time() - start_time_proc, 2)

        return {
            "success": True,
            "text": result["text"],
            "word_count": result["word_count"],
            "duration_seconds": result["duration_seconds"],
            "source": "local_whisper",
            "model_used": result["model_used"],
            "is_instant": False,
            "processing_time_seconds": elapsed,
            "range_applied": (start_seconds is not None or end_seconds is not None),
            "message": f"Transcribed section using local Whisper ({model_name})."
        }
    except Exception as e:
        logger.error(f"Error processing YouTube audio: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to transcribe YouTube audio: {str(e)}")
    finally:
        # STRICT ZERO-RETENTION
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Temporary YouTube audio completely deleted from {temp_dir}")


@app.post("/api/transcribe-audio")
async def transcribe_audio_endpoint(
    file: UploadFile = File(...),
    model: str = Form("small.en"),
    start_time: Optional[str] = Form(None),
    end_time: Optional[str] = Form(None)
):
    """
    Transcribe an uploaded audio file (or a specified section of it).
    - Streams file directly to temporary storage to handle large 60-120 minute tapes safely.
    - Slices specific section (start_time -> end_time) if provided.
    - Immediately deletes the temporary file upon completion or error.
    """
    from services.audio_extractor import parse_timestamp

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    allowed_exts = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".webm", ".wma", ".mp4"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{ext}'. Supported: {', '.join(sorted(allowed_exts))}"
        )

    try:
        start_seconds = parse_timestamp(start_time)
        end_seconds = parse_timestamp(end_time)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    if start_seconds is not None and end_seconds is not None and start_seconds >= end_seconds:
        raise HTTPException(status_code=400, detail="Start time must be earlier than End time.")

    start_time_proc = time.time()
    logger.info(f"Received audio upload: {file.filename}, model: {model}, Section: {start_seconds}s -> {end_seconds}s")

    temp_dir = tempfile.mkdtemp(prefix="stt_upload_")
    temp_file_path = os.path.join(temp_dir, f"audio_input{ext}")

    try:
        await save_upload_to_file(file, temp_file_path)
        logger.info(f"Saved uploaded audio ({os.path.getsize(temp_file_path)} bytes) to temp path")

        result = transcribe_audio(
            temp_file_path,
            model_name=model,
            language="en",
            start_seconds=start_seconds,
            end_seconds=end_seconds
        )
        elapsed = round(time.time() - start_time_proc, 2)

        return {
            "success": True,
            "filename": file.filename,
            "text": result["text"],
            "word_count": result["word_count"],
            "duration_seconds": result["duration_seconds"],
            "source": "local_whisper",
            "model_used": result["model_used"],
            "processing_time_seconds": elapsed,
            "range_applied": (start_seconds is not None or end_seconds is not None),
            "message": f"Successfully transcribed {file.filename}."
        }
    except Exception as e:
        logger.error(f"Error transcribing uploaded audio: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to transcribe audio file: {str(e)}")
    finally:
        # STRICT ZERO-RETENTION
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Temporary uploaded audio completely deleted from {temp_dir}")


# Mount static frontend
static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/")
async def serve_index():
    """Serves the main web interface."""
    index_file = os.path.join(static_path, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Speech-to-Text API is running. UI file static/index.html not found."}


if __name__ == "__main__":
    import uvicorn
    # Support large file uploads (up to 1GB for lengthy digitized tape recordings)
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
