#!/bin/bash
# ============================================================
# nginx-proxy-helper — One-line installer
#
# Usage:
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/mhiqrambg/nginx-proxy-helper/main/install.sh)"
# ============================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

INSTALL_DIR="$HOME/.nginx-proxy-helper"
REPO_URL="https://github.com/mhiqrambg/nginx-proxy-helper.git"

echo ""
echo -e "${BOLD}🔧 nginx-proxy-helper — Installer${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# ── Check prerequisites ────────────────────────────────────────

check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}✗ '$1' is not installed.${NC}"
        echo -e "  Please install $1 first, then re-run this script."
        exit 1
    fi
}

echo -e "${BOLD}[1/5]${NC} Checking prerequisites..."

check_command "git"
check_command "curl"

# Check for python3
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PY_VERSION=$(python --version 2>&1 | grep -oP '\d+' | head -1)
    if [ "$PY_VERSION" -ge 3 ]; then
        PYTHON_CMD="python"
    else
        echo -e "${RED}✗ Python 3.8+ is required but only Python 2 was found.${NC}"
        exit 1
    fi
else
    echo -e "${RED}✗ Python 3 is not installed.${NC}"
    echo -e "  Install Python 3.8+ and try again."
    exit 1
fi

PY_VERSION=$($PYTHON_CMD --version 2>&1)
echo -e "  ${GREEN}✓${NC} $PY_VERSION"
echo -e "  ${GREEN}✓${NC} git $(git --version | cut -d' ' -f3)"

# Check if venv works, auto-install on Debian/Ubuntu if missing
if ! $PYTHON_CMD -m venv --help &> /dev/null; then
    if command -v apt-get &> /dev/null; then
        echo -e "  ${YELLOW}Installing python3-venv & python3-pip via apt...${NC}"
        SUDO_CMD=""
        if [ "$EUID" -ne 0 ] && command -v sudo &> /dev/null; then
            SUDO_CMD="sudo"
        fi
        $SUDO_CMD apt-get update -qq && $SUDO_CMD apt-get install -y -qq python3-venv python3-pip &> /dev/null || true
    fi
fi

# ── Clone or update repository ─────────────────────────────────

echo ""
echo -e "${BOLD}[2/5]${NC} Installing to ${CYAN}${INSTALL_DIR}${NC}..."

if [ -d "$INSTALL_DIR" ]; then
    echo -e "  ${YELLOW}Directory already exists. Updating...${NC}"
    cd "$INSTALL_DIR"
    git pull --quiet origin main 2>/dev/null || git pull --quiet
    echo -e "  ${GREEN}✓${NC} Repository updated"
else
    git clone --quiet "$REPO_URL" "$INSTALL_DIR"
    echo -e "  ${GREEN}✓${NC} Repository cloned"
fi

cd "$INSTALL_DIR"

# ── Create virtual environment ─────────────────────────────────

echo ""
echo -e "${BOLD}[3/5]${NC} Setting up Python virtual environment..."

if [ ! -d ".venv" ]; then
    $PYTHON_CMD -m venv .venv
    echo -e "  ${GREEN}✓${NC} Virtual environment created"
else
    echo -e "  ${GREEN}✓${NC} Virtual environment already exists"
fi

source .venv/bin/activate

# ── Install package ────────────────────────────────────────────

echo ""
echo -e "${BOLD}[4/5]${NC} Installing nginx-proxy-helper and dependencies..."

pip install --quiet --upgrade pip 2>/dev/null
pip install --quiet -e . 2>/dev/null

echo -e "  ${GREEN}✓${NC} Package installed"

# ── Setup PATH ─────────────────────────────────────────────────

echo ""
echo -e "${BOLD}[5/5]${NC} Setting up PATH..."

PROXY_BIN="$INSTALL_DIR/.venv/bin/proxy"
LINK_DIR="$HOME/.local/bin"

# Create ~/.local/bin if not exists
mkdir -p "$LINK_DIR"

# Create symlink
if [ -L "$LINK_DIR/proxy" ]; then
    rm "$LINK_DIR/proxy"
fi
ln -sf "$PROXY_BIN" "$LINK_DIR/proxy"
echo -e "  ${GREEN}✓${NC} Symlink created: ${CYAN}$LINK_DIR/proxy${NC}"

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$LINK_DIR:"* ]]; then
    # Detect shell and add to rc file
    SHELL_NAME=$(basename "$SHELL")
    case "$SHELL_NAME" in
        zsh)  RC_FILE="$HOME/.zshrc" ;;
        bash) RC_FILE="$HOME/.bashrc" ;;
        fish) RC_FILE="$HOME/.config/fish/config.fish" ;;
        *)    RC_FILE="$HOME/.profile" ;;
    esac

    EXPORT_LINE='export PATH="$HOME/.local/bin:$PATH"'

    if [ -f "$RC_FILE" ] && grep -qF '.local/bin' "$RC_FILE" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} PATH already configured in ${RC_FILE}"
    else
        echo "" >> "$RC_FILE"
        echo "# nginx-proxy-helper" >> "$RC_FILE"
        echo "$EXPORT_LINE" >> "$RC_FILE"
        echo -e "  ${GREEN}✓${NC} PATH added to ${CYAN}${RC_FILE}${NC}"
    fi
fi

# ── Create docker network (optional) ──────────────────────────

if command -v docker &> /dev/null; then
    if docker network ls --format '{{.Name}}' 2>/dev/null | grep -q '^nginx-network$'; then
        echo ""
        echo -e "  ${GREEN}✓${NC} Docker network 'nginx-network' already exists"
    else
        echo ""
        echo -e "  ${YELLOW}ℹ${NC} Run this on your VPS to create the Docker network:"
        echo -e "    ${CYAN}docker network create nginx-network${NC}"
    fi
fi

# ── Done! ──────────────────────────────────────────────────────

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}✅ Installation complete!${NC}"
echo ""
echo -e "  Installed to: ${CYAN}${INSTALL_DIR}${NC}"
echo -e "  Command:      ${CYAN}proxy${NC}"
echo ""
echo -e "  ${BOLD}Quick start:${NC}"
echo -e "    ${CYAN}proxy check${NC}                  — Verify dependencies"
echo -e "    ${CYAN}proxy add-domain${NC} example.com  — Add a domain"
echo -e "    ${CYAN}proxy list${NC}                    — List all domains"
echo -e "    ${CYAN}proxy --help${NC}                  — Show all commands"
echo ""

# Remind to reload shell if PATH was updated
if [[ ":$PATH:" != *":$LINK_DIR:"* ]]; then
    echo -e "  ${YELLOW}⚠ Restart your terminal or run:${NC}"
    echo -e "    ${CYAN}source ${RC_FILE}${NC}"
    echo ""
fi
