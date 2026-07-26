"""Path configuration and settings for nginx-proxy-helper."""

import os
from pathlib import Path


def _find_project_root() -> Path:
    """Find project root by checking for nginx-alpine/ directory.

    Search order:
    1. Environment variable NGINX_PROXY_ROOT
    2. Current working directory
    3. Parent directories (up to 5 levels)
    4. Fallback to package installation directory
    """
    # 1. From environment variable
    env_root = os.environ.get("NGINX_PROXY_ROOT")
    if env_root:
        return Path(env_root)

    # 2. From CWD and parents
    cwd = Path.cwd()
    search = cwd
    for _ in range(6):
        if (search / "nginx-alpine" / "docker-compose.yml").exists():
            return search
        if search.parent == search:
            break
        search = search.parent

    # 3. Fallback: relative to package directory
    pkg_dir = Path(__file__).resolve().parent
    project_root = pkg_dir.parent
    if (project_root / "nginx-alpine" / "docker-compose.yml").exists():
        return project_root

    # 4. Use CWD as default
    return cwd


# === Project Paths ===

PROJECT_ROOT = _find_project_root()

# Docker compose project directory
COMPOSE_DIR = PROJECT_ROOT / "nginx-alpine"

# Nginx config directory
NGINX_CONF_DIR = COMPOSE_DIR / "nginx" / "conf.d"

# Certbot directories
CERTBOT_CONF_DIR = COMPOSE_DIR / "certbot" / "conf"
CERTBOT_WWW_DIR = COMPOSE_DIR / "certbot" / "www"

# Templates directory
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Backup directory for rollbacks
BACKUP_DIR = COMPOSE_DIR / ".backups"

# Nginx SSL fallback directory for catch-all default server
NGINX_SSL_DIR = COMPOSE_DIR / "nginx" / "ssl"

# === Docker Settings ===

NGINX_CONTAINER_NAME = "nginx"
CERTBOT_IMAGE = "certbot/certbot"
DOCKER_NETWORK = "nginx-network"

# === Certbot Settings ===

# Default email for Let's Encrypt (can be overridden via --email)
DEFAULT_EMAIL = os.environ.get("CERTBOT_EMAIL", "")

# Staging mode for testing (set CERTBOT_STAGING=1)
CERTBOT_STAGING = os.environ.get("CERTBOT_STAGING", "0") == "1"


def ensure_dummy_ssl_cert():
    """Generate self-signed SSL cert fallback for catch-all default server."""
    cert_file = NGINX_SSL_DIR / "dummy.crt"
    key_file = NGINX_SSL_DIR / "dummy.key"
    if not cert_file.exists() or not key_file.exists():
        import subprocess
        cmd = [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key_file), "-out", str(cert_file),
            "-days", "3650", "-subj", "/CN=default"
        ]
        subprocess.run(cmd, capture_output=True)


def ensure_directories():
    """Ensure all required directories and files exist."""
    for d in [NGINX_CONF_DIR, CERTBOT_CONF_DIR, CERTBOT_WWW_DIR, BACKUP_DIR, NGINX_SSL_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    ensure_dummy_ssl_cert()
