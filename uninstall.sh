#!/bin/bash
# ============================================================
# nginx-proxy-helper — Interactive Uninstaller
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
echo -e "${BOLD}🔧 nginx-proxy-helper — Interactive Uninstaller${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "  ${YELLOW}ℹ No installation directory found at $INSTALL_DIR${NC}"
    if [ -L "$LINK_PATH" ]; then
        rm "$LINK_PATH"
        echo -e "  ${GREEN}✓${NC} Removed symlink: $LINK_PATH"
    fi
    exit 0
fi

# If non-interactive terminal (e.g. automated pipe without tty input)
if [ ! -t 0 ]; then
    choice=1
else
    echo -e "${BOLD}How would you like to proceed with uninstallation?${NC}"
    echo ""
    echo -e "  ${BOLD}[1] Export & Keep Websites Online${NC} (Recommended)"
    echo -e "      Exports Nginx configs & SSL certs to a standalone directory (/root/nginx-alpine)"
    echo -e "      so your active websites stay ONLINE independently, then removes the CLI tool."
    echo ""
    echo -e "  ${BOLD}[2] Complete Removal${NC}"
    echo -e "      Stops Nginx & Certbot containers, creates a backup (.tar.gz), and deletes all files."
    echo ""
    echo -e "  ${BOLD}[3] Cancel Uninstallation${NC}"
    echo ""

    read -p "Select an option [1-3] (default: 1): " choice < /dev/tty || choice=1
    choice=${choice:-1}
fi

case $choice in
    1)
        EXPORT_DIR="/root/nginx-alpine"
        if [ -t 0 ]; then
            read -p "Enter export target directory [/root/nginx-alpine]: " user_dir < /dev/tty || user_dir=""
            if [ -n "$user_dir" ]; then
                EXPORT_DIR="$user_dir"
            fi
        fi

        echo ""
        echo -e "${BOLD}[1/3] Exporting standalone Nginx setup to: ${CYAN}$EXPORT_DIR${NC}"
        mkdir -p "$EXPORT_DIR"

        if [ -d "$INSTALL_DIR/nginx-alpine" ]; then
            cp -r "$INSTALL_DIR/nginx-alpine/"* "$EXPORT_DIR/" 2>/dev/null || true
            echo -e "  ${GREEN}✓${NC} Nginx configs, SSL certs, and docker-compose.yml copied to $EXPORT_DIR"
        fi

        echo ""
        echo -e "${BOLD}[2/3] Ensuring Nginx service is active in standalone directory...${NC}"
        if command -v docker &> /dev/null; then
            (cd "$EXPORT_DIR" && docker compose up -d 2>/dev/null) || true
            echo -e "  ${GREEN}✓${NC} Standalone Nginx service active in $EXPORT_DIR"
        fi

        echo ""
        echo -e "${BOLD}[3/3] Removing CLI helper files & symlink...${NC}"
        [ -L "$LINK_PATH" ] && rm "$LINK_PATH"
        [ -d "$INSTALL_DIR" ] && rm -rf "$INSTALL_DIR"
        echo -e "  ${GREEN}✓${NC} CLI tool removed"

        echo ""
        echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${GREEN}${BOLD}✅ Uninstalled successfully! Your websites remain ONLINE at:${NC}"
        echo -e "    ${CYAN}$EXPORT_DIR${NC}"
        echo -e "  Manage Nginx in future: cd $EXPORT_DIR && docker compose [up|down|reload]"
        echo ""
        ;;

    2)
        echo ""
        echo -e "${BOLD}[1/3] Stopping Nginx & Certbot Docker containers...${NC}"
        if [ -d "$INSTALL_DIR/nginx-alpine" ] && command -v docker &> /dev/null; then
            (cd "$INSTALL_DIR/nginx-alpine" && docker compose down 2>/dev/null) || true
            echo -e "  ${GREEN}✓${NC} Docker containers stopped"
        fi

        BACKUP_FILE="$HOME/nginx-proxy-helper-backup-$(date +%Y%m%d_%H%M%S).tar.gz"
        echo ""
        echo -e "${BOLD}[2/3] Creating backup archive...${NC}"
        if [ -d "$INSTALL_DIR/nginx-alpine" ]; then
            tar -czf "$BACKUP_FILE" -C "$INSTALL_DIR/nginx-alpine" nginx/conf.d certbot/conf 2>/dev/null || true
            if [ -f "$BACKUP_FILE" ]; then
                echo -e "  ${GREEN}✓${NC} Backup saved to: ${CYAN}$BACKUP_FILE${NC}"
            fi
        fi

        echo ""
        echo -e "${BOLD}[3/3] Cleaning up installation files...${NC}"
        [ -L "$LINK_PATH" ] && rm "$LINK_PATH"
        [ -d "$INSTALL_DIR" ] && rm -rf "$INSTALL_DIR"
        echo -e "  ${GREEN}✓${NC} All files removed"

        echo ""
        echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${GREEN}${BOLD}✅ Completely uninstalled.${NC}"
        if [ -f "$BACKUP_FILE" ]; then
            echo -e "  ${YELLOW}ℹ Config & SSL Backup saved at:${NC} ${CYAN}$BACKUP_FILE${NC}"
        fi
        echo ""
        ;;

    3)
        echo -e "\n${YELLOW}Uninstallation cancelled.${NC}\n"
        exit 0
        ;;

    *)
        echo -e "\n${RED}Invalid option. Uninstallation cancelled.${NC}\n"
        exit 1
        ;;
esac
