#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "========================================================"
echo "    Verbatim Transcribe: Ephemeral Speech-to-Text       "
echo "========================================================"

# Check for ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "⚠️ Warning: 'ffmpeg' was not detected on your PATH."
    echo "   Audio processing and YouTube extraction require ffmpeg."
    echo "   If not installed, run: brew install ffmpeg"
    echo "--------------------------------------------------------"
fi

# Set up virtual environment if not present
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment using Python 3.12..."
    /opt/homebrew/bin/python3.12 -m venv venv
fi

source venv/bin/activate

echo "Verifying / Installing dependencies..."
pip install -r requirements.txt

echo "========================================================"
echo " Starting Verbatim Transcribe Web Server..."
echo " Open your browser at: http://localhost:8000"
echo "========================================================"

python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
