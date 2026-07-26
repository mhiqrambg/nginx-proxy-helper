#!/bin/bash
# ============================================================
# Automatic SSL Certificate Renewal Script for Crontab
# Usage: 0 3 * * * /path/to/renew-certs.sh >> /var/log/certbot-renew.log 2>&1
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_DIR="$PROJECT_ROOT/nginx-alpine"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting SSL certificate renewal check..."

# 1. Run certbot renew via Docker Compose
cd "$COMPOSE_DIR"
docker compose run --rm --entrypoint certbot certbot renew

# 2. Reload Nginx service
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Reloading Nginx service..."
docker exec nginx nginx -s reload

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Renewal process completed successfully."
