# Verbatim Transcribe: Ephemeral Speech-to-Text

A private, high-performance transcription system designed specifically for **YouTube videos** and **digitized audio tapes (60–120+ minutes)**.

## Key Highlights

- **Word-for-Word Transcription**: Uses OpenAI Whisper via `faster-whisper` for verbatim accuracy, proper punctuation, and continuous natural paragraphs.
- **Strict Ephemeral Data Policy**:
  - No permanent audio, video, or link storage.
  - Media is held strictly in volatile temporary directories during processing.
  - Files are unconditionally purged from disk immediately after transcription finishes.
- **YouTube Dual-Path**:
  - **Instant Path (1–2 seconds)**: Automatically retrieves official or auto-generated English captions if present.
  - **Audio Fallback**: If no captions exist, downloads strictly the audio stream and runs Whisper locally.
- **Tape Audio Upload**:
  - Streams large files (MP3, WAV, M4A, FLAC, AAC, OGG) safely without loading whole files into memory.
  - Equipped with Silero Voice Activity Detection (VAD) to filter tape hiss and pauses.
- **Apple Silicon Acceleration**:
  - Optimized for Apple M2 Pro (CTranslate2 ARM NEON CPU int8), processing 1 hour of audio in just 2–3 minutes with low memory overhead.

---

## Quick Start

### 1. Prerequisites
- **Python 3.12**
- **ffmpeg** (required for audio conversion):
  ```bash
  brew install ffmpeg
  ```

### 2. Launch
Run the startup script:
```bash
./run.sh
```
Or start manually:
```bash
source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Open your browser at:
👉 **`http://localhost:8000`**

---

## Output Features
- **Continuous Paragraphs**: Text is formatted into natural reading paragraphs, ready for study, documentation, or publishing.
- **Word Count & Duration Stats**: View total words, audio duration, and elapsed processing time.
- **One-Click Copy**: Copies the full verbatim transcript to your clipboard.
- **Download as .TXT**: Saves the text file directly to your downloads folder.
- **Clear**: Instantly purges the screen and state.
