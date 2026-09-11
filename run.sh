#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "========================================================"
echo "    Verbatim Transcribe: Ephemeral Speech-to-Text       "
echo "========================================================"

# Detect operating system
OS="$(uname -s 2>/dev/null || echo "Unknown")"

# Check for ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "⚠️ Warning: 'ffmpeg' was not detected on your PATH."
    echo "   Audio processing and YouTube extraction require ffmpeg."
    echo "   Installation suggestion for your system:"
    case "$OS" in
        Darwin*)
            echo "   👉 brew install ffmpeg"
            ;;
        Linux*)
            if command -v apt-get &> /dev/null || command -v apt &> /dev/null; then
                echo "   👉 sudo apt update && sudo apt install -y ffmpeg"
            elif command -v dnf &> /dev/null; then
                echo "   👉 sudo dnf install -y ffmpeg"
            elif command -v pacman &> /dev/null; then
                echo "   👉 sudo pacman -S ffmpeg"
            elif command -v zypper &> /dev/null; then
                echo "   👉 sudo zypper install ffmpeg"
            elif command -v apk &> /dev/null; then
                echo "   👉 sudo apk add ffmpeg"
            else
                echo "   👉 Install 'ffmpeg' using your distribution's package manager."
            fi
            ;;
        MINGW*|MSYS*|CYGWIN*)
            echo "   👉 winget install Gyan.FFmpeg   (or: choco install ffmpeg)"
            ;;
        *)
            echo "   👉 Install ffmpeg from https://ffmpeg.org/download.html"
            ;;
    esac
    echo "--------------------------------------------------------"
fi

# Function to discover a compatible Python 3 interpreter
find_python() {
    # 1. Check custom PYTHON environment variable if provided
    if [ -n "$PYTHON" ]; then
        if $PYTHON -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
            echo "$PYTHON"
            return 0
        fi
    fi

    # 2. Preferred Python versions (3.9 - 3.12 recommended for CTranslate2 / faster-whisper)
    local candidates=("python3.12" "python3.11" "python3.10" "python3.9" "python3" "python")
    for cmd in "${candidates[@]}"; do
        if command -v "$cmd" &> /dev/null; then
            if "$cmd" -c 'import sys; sys.exit(0 if (3, 9) <= sys.version_info < (3, 14) else 1)' 2>/dev/null; then
                echo "$cmd"
                return 0
            fi
        fi
    done

    # 3. Check Windows py launcher if present
    if command -v py &> /dev/null; then
        for ver in "-3.12" "-3.11" "-3.10" "-3.9" "-3"; do
            if py "$ver" -c 'import sys; sys.exit(0 if (3, 9) <= sys.version_info < (3, 14) else 1)' 2>/dev/null; then
                echo "py $ver"
                return 0
            fi
        done
    fi

    # 4. Fallback: Any Python 3 >= 3.9
    for cmd in "${candidates[@]}"; do
        if command -v "$cmd" &> /dev/null; then
            if "$cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
                echo "$cmd"
                return 0
            fi
        fi
    done

    return 1
}

# Set up virtual environment if not present
if [ ! -d "venv" ]; then
    PY_BIN="$(find_python || true)"

    if [ -z "$PY_BIN" ]; then
        echo "❌ Error: A compatible Python 3 interpreter (Python 3.9 – 3.12 recommended) was not found."
        echo "   Please install Python 3.12:"
        case "$OS" in
            Darwin*)
                echo "   👉 brew install python@3.12"
                ;;
            Linux*)
                if command -v apt-get &> /dev/null || command -v apt &> /dev/null; then
                    echo "   👉 sudo apt update && sudo apt install -y python3.12 python3.12-venv python3-pip"
                elif command -v dnf &> /dev/null; then
                    echo "   👉 sudo dnf install -y python3.12 python3.12-pip"
                elif command -v pacman &> /dev/null; then
                    echo "   👉 sudo pacman -S python python-pip"
                else
                    echo "   👉 Install Python 3.12 and python3-venv using your package manager."
                fi
                ;;
            MINGW*|MSYS*|CYGWIN*)
                echo "   👉 winget install Python.Python.3.12   (or download from https://www.python.org)"
                ;;
            *)
                echo "   👉 Download from https://www.python.org/downloads/"
                ;;
        esac
        exit 1
    fi

    read -r -a PY_CMD <<< "$PY_BIN"
    PY_VER="$("${PY_CMD[@]}" --version 2>&1)"
    echo "Creating Python virtual environment using $PY_BIN ($PY_VER)..."

    if ! "${PY_CMD[@]}" -m venv venv; then
        echo "❌ Failed to create virtual environment."
        if [[ "$OS" == Linux* ]] && (command -v apt-get &> /dev/null || command -v apt &> /dev/null); then
            echo "   On Debian/Ubuntu, venv requires an extra package:"
            echo "   👉 sudo apt install -y python3-venv (or python3.12-venv)"
        fi
        exit 1
    fi
fi

# Activate virtual environment (POSIX vs Windows Git Bash / MSYS)
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
else
    echo "❌ Error: Virtual environment activation script not found in venv/bin or venv/Scripts."
    exit 1
fi

echo "Verifying / Installing dependencies..."
python -m pip install -r requirements.txt

# Configurable host and port
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

echo "========================================================"
echo " Starting Verbatim Transcribe Web Server..."
echo " Open your browser at: http://${HOST}:${PORT}"
echo "========================================================"

python -m uvicorn main:app --host "$HOST" --port "$PORT" --reload
