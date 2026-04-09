#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# StemForge — Full System Install Script for macOS
# Run: chmod +x install.sh && ./install.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PYTHON_VERSION="3.11.11"
STEMFORGE_DIR="$(cd "$(dirname "$0")" && pwd)"
STEMFORGE_ROOT="$HOME/stemforge"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           StemForge — Full System Install                   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── 1. Homebrew ──────────────────────────────────────────────────────────────
echo "▸ [1/7] Checking Homebrew..."
if ! command -v brew &>/dev/null; then
    echo "  Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for Apple Silicon or Intel
    if [ -f /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -f /usr/local/bin/brew ]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
else
    echo "  Homebrew OK"
fi

# ── 2. pyenv ─────────────────────────────────────────────────────────────────
echo "▸ [2/7] Checking pyenv..."
if ! command -v pyenv &>/dev/null; then
    echo "  Installing pyenv..."
    brew install pyenv
fi

# Make sure pyenv is initialized for this script
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims:$PATH"
eval "$(pyenv init -)"
echo "  pyenv OK"

# ── 3. Python 3.11 ──────────────────────────────────────────────────────────
echo "▸ [3/7] Checking Python $PYTHON_VERSION..."
if ! pyenv versions --bare | grep -q "^${PYTHON_VERSION}$"; then
    echo "  Installing Python $PYTHON_VERSION (this takes a few minutes)..."
    pyenv install "$PYTHON_VERSION"
fi
echo "  Python $PYTHON_VERSION OK"

# Set local python version for the project
cd "$STEMFORGE_DIR"
pyenv local "$PYTHON_VERSION"

# ── 4. uv ────────────────────────────────────────────────────────────────────
echo "▸ [4/7] Checking uv..."
if ! command -v uv &>/dev/null; then
    echo "  Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "  uv OK"

# ── 5. Virtual environment + dependencies ────────────────────────────────────
echo "▸ [5/7] Setting up virtual environment..."
cd "$STEMFORGE_DIR"

if [ -d .venv ]; then
    echo "  Removing existing .venv..."
    rm -rf .venv
fi

uv venv --python "$PYTHON_VERSION"
source .venv/bin/activate

echo "  Installing core dependencies..."
# Pin numba/llvmlite (prebuilt wheels) and numpy<2 (torch 2.2 compat)
uv pip install "numpy<2" "llvmlite==0.43.0" "numba==0.60.0"

echo "  Installing stemforge..."
uv pip install -e .

echo "  Installing local Demucs backend (torch + torchaudio + demucs)..."
uv pip install torch torchaudio demucs

# ── 6. Create folder structure ───────────────────────────────────────────────
echo "▸ [6/7] Creating folder structure..."
mkdir -p "$STEMFORGE_ROOT/inbox"
mkdir -p "$STEMFORGE_ROOT/processed"
mkdir -p "$STEMFORGE_ROOT/logs"
echo "  $STEMFORGE_ROOT/inbox/"
echo "  $STEMFORGE_ROOT/processed/"
echo "  $STEMFORGE_ROOT/logs/"

# ── 7. Generate pipeline JSON ───────────────────────────────────────────────
echo "▸ [7/7] Generating pipeline JSON for M4L device..."
stemforge generate-pipeline-json

# ── Shell config ─────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Detect shell config file
SHELL_RC=""
if [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
elif [ -f "$HOME/.bash_profile" ]; then
    SHELL_RC="$HOME/.bash_profile"
fi

NEEDS_SHELL_UPDATE=false

if [ -n "$SHELL_RC" ]; then
    # Check if pyenv init is already in shell config
    if ! grep -q 'pyenv init' "$SHELL_RC" 2>/dev/null; then
        NEEDS_SHELL_UPDATE=true
        echo "Add these lines to $SHELL_RC for pyenv + uv to work in new terminals:"
        echo ""
        echo '  # pyenv'
        echo '  export PYENV_ROOT="$HOME/.pyenv"'
        echo '  export PATH="$PYENV_ROOT/bin:$PATH"'
        echo '  eval "$(pyenv init -)"'
        echo ""
    fi
    if ! grep -q '.local/bin' "$SHELL_RC" 2>/dev/null; then
        NEEDS_SHELL_UPDATE=true
        echo '  # uv'
        echo '  export PATH="$HOME/.local/bin:$PATH"'
        echo ""
    fi
fi

# ── Verify ───────────────────────────────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "▸ Verifying installation..."
echo ""

PASS=true

# Check CLI
if python -c "from stemforge.cli import cli; print('  ✓ CLI import OK')"; then
    :
else
    echo "  ✗ CLI import FAILED"
    PASS=false
fi

# Check stemforge command
if stemforge list &>/dev/null; then
    echo "  ✓ stemforge list OK"
else
    echo "  ✗ stemforge list FAILED"
    PASS=false
fi

# Check torch
if python -c "import torch; print('  ✓ torch OK — MPS:', torch.backends.mps.is_available())"; then
    :
else
    echo "  ✗ torch FAILED"
    PASS=false
fi

# Check demucs
if python -c "import demucs; print('  ✓ demucs OK')"; then
    :
else
    echo "  ✗ demucs FAILED"
    PASS=false
fi

# Check pipeline JSON
if python -c "import json; json.load(open('pipelines/default.json')); print('  ✓ pipelines/default.json OK')"; then
    :
else
    echo "  ✗ pipelines/default.json FAILED"
    PASS=false
fi

# Check M4L files
if [ -f m4l/stemforge_loader.js ] && [ -f m4l/README_M4L.md ]; then
    echo "  ✓ M4L files OK"
else
    echo "  ✗ M4L files MISSING"
    PASS=false
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if $PASS; then
    echo ""
    echo "  ✓ StemForge installed successfully!"
    echo ""
    echo "  Quick start:"
    echo "    cd $STEMFORGE_DIR"
    echo "    source .venv/bin/activate"
    echo "    stemforge split ~/stemforge/inbox/track.wav"
    echo ""
    echo "  Next: follow setup.md to build Ableton template tracks"
    echo ""
else
    echo ""
    echo "  ✗ Some checks failed — see above"
    echo ""
fi
