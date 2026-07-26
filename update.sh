#!/bin/bash
# ============================================================
# nginx-proxy-helper — Updater
#
# Usage:
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/mhiqrambg/nginx-proxy-helper/main/update.sh)"
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

INSTALL_DIR="$HOME/.nginx-proxy-helper"

echo ""
echo -e "${BOLD}🔧 nginx-proxy-helper — Updater${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check if installed
if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${RED}✗ nginx-proxy-helper is not installed at ${INSTALL_DIR}${NC}"
    echo -e "  Run the install script first:"
    echo -e "  ${CYAN}/bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/mhiqrambg/nginx-proxy-helper/main/install.sh)\"${NC}"
    exit 1
fi

cd "$INSTALL_DIR"

# Get current version
OLD_VERSION=$(grep -oP '(?<=__version__ = ")[^"]+' nginx_proxy_helper/__init__.py 2>/dev/null || echo "unknown")

# Pull latest
echo -e "${BOLD}[1/3]${NC} Pulling latest changes..."
git fetch --quiet origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo -e "  ${GREEN}✓${NC} Already up to date (v${OLD_VERSION})"
    echo ""
    exit 0
fi

git pull --quiet origin main
echo -e "  ${GREEN}✓${NC} Repository updated"

# Reinstall
echo -e "${BOLD}[2/3]${NC} Reinstalling package..."
source .venv/bin/activate
pip install --quiet --upgrade pip 2>/dev/null
pip install --quiet -e . 2>/dev/null
echo -e "  ${GREEN}✓${NC} Package reinstalled"

# Get new version
NEW_VERSION=$(grep -oP '(?<=__version__ = ")[^"]+' nginx_proxy_helper/__init__.py 2>/dev/null || echo "unknown")

# Verify
echo -e "${BOLD}[3/3]${NC} Verifying..."
PROXY_VERSION=$(.venv/bin/proxy --version 2>&1 || true)
echo -e "  ${GREEN}✓${NC} $PROXY_VERSION"

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}✅ Update complete!${NC}"
echo -e "  ${OLD_VERSION} → ${NEW_VERSION}"
echo ""
