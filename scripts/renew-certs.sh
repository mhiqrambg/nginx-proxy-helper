#!/bin/bash
# ============================================================
# renew-certs.sh
# Script untuk auto-renew SSL certificates via crontab
#
# Setup crontab (renew setiap hari jam 3 pagi):
#   0 3 * * * /path/to/nginx-proxy-helper/scripts/renew-certs.sh >> /var/log/certbot-renew.log 2>&1
# ============================================================

set -e

# Navigasi ke project directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_DIR="$PROJECT_DIR/nginx-alpine"

echo "============================================"
echo "Certbot Auto-Renewal — $(date)"
echo "============================================"

# Renew certificates
echo "[1/2] Renewing certificates..."
docker compose -f "$COMPOSE_DIR/docker-compose.yml" run --rm certbot renew

# Reload nginx
echo "[2/2] Reloading nginx..."
docker exec nginx nginx -s reload

echo "✓ Renewal complete — $(date)"
echo ""
