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

# 1. Stop Docker Compose services gracefully if running
if [ -d "$INSTALL_DIR/nginx-alpine" ]; then
    echo -e "${BOLD}[1/3]${NC} Stopping Nginx & Certbot Docker containers..."
    if command -v docker &> /dev/null; then
        (cd "$INSTALL_DIR/nginx-alpine" && docker compose down 2>/dev/null) || true
        echo -e "  ${GREEN}✓${NC} Docker containers stopped & removed cleanly"
    fi
fi

# 2. Create a backup of configs & certificates before removing
BACKUP_FILE="$HOME/nginx-proxy-helper-backup-$(date +%Y%m%d_%H%M%S).tar.gz"
if [ -d "$INSTALL_DIR/nginx-alpine" ]; then
    echo ""
    echo -e "${BOLD}[2/3]${NC} Backing up Nginx configs & SSL certificates..."
    tar -czf "$BACKUP_FILE" -C "$INSTALL_DIR/nginx-alpine" nginx/conf.d certbot/conf 2>/dev/null || true
    if [ -f "$BACKUP_FILE" ]; then
        echo -e "  ${GREEN}✓${NC} Backup saved to: ${CYAN}$BACKUP_FILE${NC}"
    fi
fi

# 3. Remove symlink & install directory
echo ""
echo -e "${BOLD}[3/3]${NC} Cleaning up files & symlinks..."

if [ -L "$LINK_PATH" ]; then
    rm "$LINK_PATH"
    echo -e "  ${GREEN}✓${NC} Removed symlink: $LINK_PATH"
else
    echo -e "  ${YELLOW}ℹ${NC} No symlink found at $LINK_PATH"
fi

if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    echo -e "  ${GREEN}✓${NC} Removed directory: $INSTALL_DIR"
else
    echo -e "  ${YELLOW}ℹ${NC} No installation directory found at $INSTALL_DIR"
fi

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}✅ nginx-proxy-helper has been completely uninstalled.${NC}"
if [ -f "$BACKUP_FILE" ]; then
    echo -e "  ${YELLOW}ℹ Your Nginx configs & SSL certs backup is saved at:${NC}"
    echo -e "    ${CYAN}$BACKUP_FILE${NC}"
fi
echo ""
