#!/bin/bash
# ============================================================
# nginx-proxy-helper — Uninstaller
#
# Usage:
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/mhiqrambg/nginx-proxy-helper/main/uninstall.sh)"
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

INSTALL_DIR="$HOME/.nginx-proxy-helper"
LINK_PATH="$HOME/.local/bin/proxy"

echo ""
echo -e "${BOLD}🔧 nginx-proxy-helper — Uninstaller${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Remove symlink
if [ -L "$LINK_PATH" ]; then
    rm "$LINK_PATH"
    echo -e "  ${GREEN}✓${NC} Removed symlink: $LINK_PATH"
else
    echo -e "  ${YELLOW}ℹ${NC} No symlink found at $LINK_PATH"
fi

# Remove install directory
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    echo -e "  ${GREEN}✓${NC} Removed directory: $INSTALL_DIR"
else
    echo -e "  ${YELLOW}ℹ${NC} No installation found at $INSTALL_DIR"
fi

echo ""
echo -e "${GREEN}${BOLD}✅ nginx-proxy-helper has been uninstalled.${NC}"
echo ""
