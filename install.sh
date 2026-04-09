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

# ── 0. Ableton directories ──────────────────────────────────────────────────
# Detect defaults, let user override

DEFAULT_ABLETON_USER_LIB="$HOME/Music/Ableton/User Library"
DEFAULT_ABLETON_PROJECTS="$HOME/Music/Ableton/Projects"
DEFAULT_VST3_DIR="$HOME/Library/Audio/Plug-Ins/VST3"

echo "▸ [0/8] Ableton Live configuration"
echo ""
echo "  StemForge needs to know where your Ableton directories are."
echo "  Press Enter to accept the default, or type a custom path."
echo ""

read -rp "  Ableton User Library [$DEFAULT_ABLETON_USER_LIB]: " ABLETON_USER_LIB
ABLETON_USER_LIB="${ABLETON_USER_LIB:-$DEFAULT_ABLETON_USER_LIB}"

read -rp "  Ableton Projects dir [$DEFAULT_ABLETON_PROJECTS]: " ABLETON_PROJECTS
ABLETON_PROJECTS="${ABLETON_PROJECTS:-$DEFAULT_ABLETON_PROJECTS}"

read -rp "  VST3 Plug-Ins dir [$DEFAULT_VST3_DIR]: " VST3_DIR
VST3_DIR="${VST3_DIR:-$DEFAULT_VST3_DIR}"

echo ""
echo "  User Library:  $ABLETON_USER_LIB"
echo "  Projects:      $ABLETON_PROJECTS"
echo "  VST3:          $VST3_DIR"
echo ""

# Validate directories exist
for dir_label_pair in "User Library:$ABLETON_USER_LIB" "Projects:$ABLETON_PROJECTS"; do
    label="${dir_label_pair%%:*}"
    dir="${dir_label_pair#*:}"
    if [ ! -d "$dir" ]; then
        echo "  ⚠  $label dir not found: $dir"
        read -rp "  Create it? [Y/n]: " create_it
        if [[ "${create_it:-Y}" =~ ^[Yy] ]]; then
            mkdir -p "$dir"
            echo "  Created: $dir"
        fi
    fi
done

# Save paths for later use by stemforge and M4L
STEMFORGE_CONF="$STEMFORGE_ROOT/.config"
mkdir -p "$STEMFORGE_ROOT"
cat > "$STEMFORGE_CONF" <<CONF
# StemForge paths — written by install.sh
ABLETON_USER_LIB=$ABLETON_USER_LIB
ABLETON_PROJECTS=$ABLETON_PROJECTS
VST3_DIR=$VST3_DIR
STEMFORGE_DIR=$STEMFORGE_DIR
CONF
echo "  Paths saved to $STEMFORGE_CONF"
echo ""

# ── 1. Homebrew ──────────────────────────────────────────────────────────────
echo "▸ [1/8] Checking Homebrew..."
if ! command -v brew &>/dev/null; then
    echo "  Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [ -f /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -f /usr/local/bin/brew ]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
else
    echo "  Homebrew OK"
fi

# ── 2. pyenv ─────────────────────────────────────────────────────────────────
echo "▸ [2/8] Checking pyenv..."
if ! command -v pyenv &>/dev/null; then
    echo "  Installing pyenv..."
    brew install pyenv
fi

export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims:$PATH"
eval "$(pyenv init -)"
echo "  pyenv OK"

# ── 3. Python 3.11 ──────────────────────────────────────────────────────────
echo "▸ [3/8] Checking Python $PYTHON_VERSION..."
if ! pyenv versions --bare | grep -q "^${PYTHON_VERSION}$"; then
    echo "  Installing Python $PYTHON_VERSION (this takes a few minutes)..."
    pyenv install "$PYTHON_VERSION"
fi
echo "  Python $PYTHON_VERSION OK"

cd "$STEMFORGE_DIR"
pyenv local "$PYTHON_VERSION"

# ── 4. uv ────────────────────────────────────────────────────────────────────
echo "▸ [4/8] Checking uv..."
if ! command -v uv &>/dev/null; then
    echo "  Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "  uv OK"

# ── 5. Virtual environment + dependencies ────────────────────────────────────
echo "▸ [5/8] Setting up virtual environment..."
cd "$STEMFORGE_DIR"

if [ -d .venv ]; then
    echo "  Removing existing .venv..."
    rm -rf .venv
fi

uv venv --python "$PYTHON_VERSION"
source .venv/bin/activate

echo "  Installing core dependencies..."
uv pip install "numpy<2" "llvmlite==0.43.0" "numba==0.60.0"

echo "  Installing stemforge..."
uv pip install -e .

echo "  Installing local Demucs backend (torch + torchaudio + demucs)..."
uv pip install torch torchaudio demucs

# ── 6. Create folder structure ───────────────────────────────────────────────
echo "▸ [6/8] Creating folder structure..."
mkdir -p "$STEMFORGE_ROOT/inbox"
mkdir -p "$STEMFORGE_ROOT/processed"
mkdir -p "$STEMFORGE_ROOT/logs"
echo "  $STEMFORGE_ROOT/inbox/"
echo "  $STEMFORGE_ROOT/processed/"
echo "  $STEMFORGE_ROOT/logs/"

# ── 7. Generate pipeline JSON + install M4L device ──────────────────────────
echo "▸ [7/8] Generating pipeline JSON + installing M4L device..."
stemforge generate-pipeline-json

# Copy M4L device + JS to Ableton User Library
M4L_DEST="$ABLETON_USER_LIB/Presets/MIDI Effects/Max MIDI Effect/StemForge"
mkdir -p "$M4L_DEST"
cp "$STEMFORGE_DIR/m4l/stemforge_loader.js" "$M4L_DEST/"

# Generate a Max patch description file for reference
cp "$STEMFORGE_DIR/m4l/README_M4L.md" "$M4L_DEST/"

echo "  M4L files installed to: $M4L_DEST"
echo ""
echo "  ┌─────────────────────────────────────────────────────────┐"
echo "  │ NOTE: You still need to build the .amxd patch in Max.  │"
echo "  │ See m4l/README_M4L.md for the patch wiring diagram.    │"
echo "  │ Save the device into: $M4L_DEST"
echo "  └─────────────────────────────────────────────────────────┘"

# Create the StemForge Templates project folder
SF_TEMPLATES_DIR="$ABLETON_PROJECTS/StemForge Templates"
if [ ! -d "$SF_TEMPLATES_DIR" ]; then
    mkdir -p "$SF_TEMPLATES_DIR"
    echo "  Created Ableton project folder: $SF_TEMPLATES_DIR"
    echo "  Open Ableton → File → New Live Set → Save As into this folder."
else
    echo "  Ableton project folder already exists: $SF_TEMPLATES_DIR"
fi

# Symlink pipelines into the M4L device folder so it can find them
if [ ! -L "$M4L_DEST/pipelines" ]; then
    ln -sf "$STEMFORGE_DIR/pipelines" "$M4L_DEST/pipelines"
    echo "  Symlinked pipelines → $M4L_DEST/pipelines"
fi

# ── 8. Shell config ─────────────────────────────────────────────────────────
echo "▸ [8/8] Checking shell config..."

SHELL_RC=""
if [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
elif [ -f "$HOME/.bash_profile" ]; then
    SHELL_RC="$HOME/.bash_profile"
fi

NEEDS_SHELL_UPDATE=false
SHELL_ADDITIONS=""

if [ -n "$SHELL_RC" ]; then
    if ! grep -q 'pyenv init' "$SHELL_RC" 2>/dev/null; then
        NEEDS_SHELL_UPDATE=true
        SHELL_ADDITIONS+=$'\n# pyenv\nexport PYENV_ROOT="$HOME/.pyenv"\nexport PATH="$PYENV_ROOT/bin:$PATH"\neval "$(pyenv init -)"\n'
    fi
    if ! grep -q '.local/bin' "$SHELL_RC" 2>/dev/null; then
        NEEDS_SHELL_UPDATE=true
        SHELL_ADDITIONS+=$'\n# uv\nexport PATH="$HOME/.local/bin:$PATH"\n'
    fi
    if ! grep -q 'stemforge' "$SHELL_RC" 2>/dev/null; then
        NEEDS_SHELL_UPDATE=true
        SHELL_ADDITIONS+=$'\n# stemforge\nalias sf=\"cd '"$STEMFORGE_DIR"' && source .venv/bin/activate\"\n'
    fi
fi

if $NEEDS_SHELL_UPDATE && [ -n "$SHELL_RC" ]; then
    echo ""
    echo "  The following will be added to $SHELL_RC:"
    echo "$SHELL_ADDITIONS"
    read -rp "  Add these lines? [Y/n]: " add_lines
    if [[ "${add_lines:-Y}" =~ ^[Yy] ]]; then
        echo "$SHELL_ADDITIONS" >> "$SHELL_RC"
        echo "  Updated $SHELL_RC"
    else
        echo "  Skipped. Add them manually if needed."
    fi
fi

# ── Verify ───────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "▸ Verifying installation..."
echo ""

PASS=true

if python -c "from stemforge.cli import cli; print('  ✓ CLI import OK')"; then
    :
else
    echo "  ✗ CLI import FAILED"
    PASS=false
fi

if stemforge list &>/dev/null; then
    echo "  ✓ stemforge list OK"
else
    echo "  ✗ stemforge list FAILED"
    PASS=false
fi

if python -c "import torch; print('  ✓ torch OK — MPS:', torch.backends.mps.is_available())"; then
    :
else
    echo "  ✗ torch FAILED"
    PASS=false
fi

if python -c "import demucs; print('  ✓ demucs OK')"; then
    :
else
    echo "  ✗ demucs FAILED"
    PASS=false
fi

if python -c "import json; json.load(open('pipelines/default.json')); print('  ✓ pipelines/default.json OK')"; then
    :
else
    echo "  ✗ pipelines/default.json FAILED"
    PASS=false
fi

if [ -f m4l/stemforge_loader.js ] && [ -f m4l/README_M4L.md ]; then
    echo "  ✓ M4L files OK"
else
    echo "  ✗ M4L files MISSING"
    PASS=false
fi

if [ -d "$M4L_DEST" ] && [ -f "$M4L_DEST/stemforge_loader.js" ]; then
    echo "  ✓ M4L installed to Ableton User Library"
else
    echo "  ✗ M4L not in Ableton User Library"
    PASS=false
fi

if [ -L "$M4L_DEST/pipelines" ]; then
    echo "  ✓ Pipelines symlinked into M4L folder"
else
    echo "  ✗ Pipelines symlink missing"
    PASS=false
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if $PASS; then
    echo ""
    echo "  ✓ StemForge installed successfully!"
    echo ""
    echo "  Paths:"
    echo "    Stemforge repo:    $STEMFORGE_DIR"
    echo "    Working dir:       $STEMFORGE_ROOT"
    echo "    Inbox:             $STEMFORGE_ROOT/inbox/"
    echo "    Output:            $STEMFORGE_ROOT/processed/"
    echo "    M4L device:        $M4L_DEST"
    echo "    Templates project: $SF_TEMPLATES_DIR"
    echo "    Pipelines:         $STEMFORGE_DIR/pipelines/"
    echo ""
    echo "  Quick start:"
    echo "    sf                 # alias: cd + activate venv"
    echo "    stemforge split ~/stemforge/inbox/track.wav"
    echo ""
    echo "  Next steps:"
    echo "    1. Open Ableton → build template tracks (see setup.md)"
    echo "    2. Build the M4L device in Max (see m4l/README_M4L.md)"
    echo "    3. Drop a WAV in ~/stemforge/inbox/ and run stemforge split"
    echo ""
else
    echo ""
    echo "  ✗ Some checks failed — see above"
    echo ""
fi
