#!/usr/bin/env bash
# setup.sh — One-shot setup for phingr-cli.
#
# Creates Python venv and installs dependencies.
# Safe to re-run — skips completed steps.
#
# Usage:
#   bash setup.sh          # setup only
#   bash setup.sh run      # setup + start server

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
REQ_FILE="$SCRIPT_DIR/requirements.txt"
MARKER="$VENV_DIR/.phingr-cli-installed"

echo "============================================"
echo " phingr-cli Setup"
echo "============================================"
echo ""

# ── 1. Check Python ─────────────────────────────────────────────────────

PYTHON=""
for candidate in python3.12 python3.13 python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
        PY_MINOR=$("$candidate" -c "import sys; print(sys.version_info.minor)")
        if [ "$PY_MINOR" -ge 10 ] && [ "$PY_MINOR" -le 13 ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.10-3.13 required."
    echo "  macOS: brew install python@3.13"
    exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[1/4] Python: $PYTHON ($PY_VERSION)"

# ── 2. Install system dependencies ────────────────────────────────────

echo -n "[2/4] Tesseract OCR: "
if command -v tesseract &>/dev/null; then
    echo "already installed"
else
    echo "installing..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        if command -v brew &>/dev/null; then
            brew install tesseract -q 2>/dev/null
        else
            echo "  WARNING: Install Tesseract manually: brew install tesseract"
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if command -v apt-get &>/dev/null; then
            sudo apt-get install -y -qq tesseract-ocr >/dev/null 2>&1
        elif command -v dnf &>/dev/null; then
            sudo dnf install -y -q tesseract >/dev/null 2>&1
        else
            echo "  WARNING: Install Tesseract manually"
        fi
    fi
    if command -v tesseract &>/dev/null; then
        echo "  Done"
    else
        echo "  WARNING: Tesseract not installed — OCR text matching will be unavailable"
    fi
fi

# ── 3. Create virtual environment ──────────────────────────────────────

if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/activate" ]; then
    echo "[3/4] Virtual environment already exists"
else
    echo "[2/3] Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# ── 3. Install dependencies ────────────────────────────────────────────

REQ_HASH=$(md5sum "$REQ_FILE" 2>/dev/null | awk '{print $1}' || md5 -q "$REQ_FILE" 2>/dev/null || echo "unknown")

if [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$REQ_HASH" ]; then
    echo "[4/4] Dependencies up to date"
else
    echo "[4/4] Installing dependencies..."
    pip install --upgrade pip -q 2>/dev/null
    pip install -r "$REQ_FILE" -q
    echo "$REQ_HASH" > "$MARKER"
    echo "  Done"
fi

deactivate 2>/dev/null || true

# Copy example flows if data/flows is empty
FLOWS_DIR="$SCRIPT_DIR/data/flows"
mkdir -p "$FLOWS_DIR"
if [ -z "$(ls -A "$FLOWS_DIR" 2>/dev/null)" ]; then
    echo "  Copying example flows..."
    cp "$SCRIPT_DIR/examples/"*.yaml "$FLOWS_DIR/" 2>/dev/null || true
fi

# ── Done ────────────────────────────────────────────────────────────────

DEVICE_URL="${PHINGR_DEVICE_URL:-http://localhost:8080}"

echo ""
echo "============================================"
echo " Setup Complete"
echo "============================================"
echo ""
echo "  Start server:"
echo "    bash setup.sh run"
echo ""
echo "  Device URL:  $DEVICE_URL"
echo "  Web UI:      http://localhost:8800"
echo ""

# ── Optional: run server ────────────────────────────────────────────────

if [ "${1:-}" = "run" ]; then
    CLI_PORT="${CLI_PORT:-8800}"

    # Kill existing server on this port
    lsof -ti:"$CLI_PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
    sleep 1

    echo "Starting phingr-cli server (port $CLI_PORT)..."
    source "$VENV_DIR/bin/activate"
    cd "$SCRIPT_DIR"
    exec python3 -m uvicorn app.server:app --host 0.0.0.0 --port "$CLI_PORT"
fi
