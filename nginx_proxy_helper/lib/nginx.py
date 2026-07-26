"""Nginx helper — generate config, test, dan reload nginx."""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader
from rich.console import Console

from nginx_proxy_helper.config import (
    BACKUP_DIR,
    NGINX_CONF_DIR,
    NGINX_CONTAINER_NAME,
    TEMPLATES_DIR,
)
from nginx_proxy_helper.lib.docker import docker_exec, DockerError

console = Console()

# Jinja2 environment
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    keep_trailing_newline=True,
)


# ── Config Generation ──────────────────────────────────────────────


def render_http_challenge_config(domain: str, www: bool = False) -> str:
    """Render HTTP-only config untuk ACME challenge.

    Args:
        domain: Domain name.
        www: Jika True, tambahkan www.domain sebagai server_name.

    Returns:
        Rendered nginx config string.
    """
    template = _env.get_template("http_challenge.conf.j2")
    return template.render(domain=domain, www=www)


def render_ssl_config(
    domain: str,
    target: str,
    www: bool = False,
    cert_domain: Optional[str] = None,
) -> str:
    """Render full SSL reverse proxy config.

    Args:
        domain: Domain name.
        target: Proxy target (e.g., "app:3000").
        www: Jika True, tambahkan www.domain sebagai server_name.
        cert_domain: Domain untuk path sertifikat. Default = domain.

    Returns:
        Rendered nginx config string.
    """
    if cert_domain is None:
        cert_domain = domain

    template = _env.get_template("ssl_proxy.conf.j2")
    return template.render(
        domain=domain,
        target=target,
        www=www,
        cert_domain=cert_domain,
    )


# ── Config File Operations ─────────────────────────────────────────


def config_path(domain: str) -> Path:
    """Dapatkan path file config untuk domain."""
    return NGINX_CONF_DIR / f"{domain}.conf"


def config_exists(domain: str) -> bool:
    """Cek apakah config file untuk domain sudah ada."""
    return config_path(domain).exists()


def write_config(domain: str, content: str) -> Path:
    """Tulis config file untuk domain.

    Args:
        domain: Domain name.
        content: Config content.

    Returns:
        Path ke file config yang ditulis.
    """
    NGINX_CONF_DIR.mkdir(parents=True, exist_ok=True)
    path = config_path(domain)
    path.write_text(content)
    console.print(f"[green]✓[/green] Config written: [cyan]{path}[/cyan]")
    return path


def remove_config(domain: str) -> bool:
    """Hapus config file untuk domain.

    Args:
        domain: Domain name.

    Returns:
        True jika file berhasil dihapus, False jika tidak ada.
    """
    path = config_path(domain)
    if path.exists():
        path.unlink()
        console.print(f"[green]✓[/green] Config removed: [cyan]{path}[/cyan]")
        return True
    return False


# ── Backup & Rollback ──────────────────────────────────────────────


def backup_config(domain: str) -> Optional[Path]:
    """Backup config file sebelum modifikasi.

    Args:
        domain: Domain name.

    Returns:
        Path ke backup file, atau None jika tidak ada config yang di-backup.
    """
    src = config_path(domain)
    if not src.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"{domain}.conf.{timestamp}.bak"
    shutil.copy2(src, backup_path)
    console.print(f"[dim]Backup created: {backup_path.name}[/dim]")
    return backup_path


def restore_config(domain: str, backup_path: Path) -> None:
    """Restore config dari backup.

    Args:
        domain: Domain name.
        backup_path: Path ke backup file.
    """
    dst = config_path(domain)
    shutil.copy2(backup_path, dst)
    console.print(f"[yellow]⟲ Config restored from backup: {backup_path.name}[/yellow]")


def cleanup_old_backups(domain: str, keep: int = 5) -> None:
    """Hapus backup lama, simpan hanya N terbaru.

    Args:
        domain: Domain name.
        keep: Jumlah backup yang disimpan.
    """
    if not BACKUP_DIR.exists():
        return

    backups = sorted(
        BACKUP_DIR.glob(f"{domain}.conf.*.bak"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[keep:]:
        old.unlink()


# ── Nginx Docker Operations ────────────────────────────────────────


def test_nginx_config() -> tuple[bool, str]:
    """Test konfigurasi nginx.

    Returns:
        Tuple of (success, output_message).
    """
    try:
        result = docker_exec(NGINX_CONTAINER_NAME, "nginx -t")
        output = (result.stderr or result.stdout or "").strip()
        return True, output
    except DockerError as e:
        return False, str(e)


def reload_nginx() -> tuple[bool, str]:
    """Reload nginx setelah config berubah.

    Returns:
        Tuple of (success, output_message).
    """
    try:
        result = docker_exec(NGINX_CONTAINER_NAME, "nginx -s reload")
        output = (result.stderr or result.stdout or "").strip()
        return True, output or "Nginx reloaded successfully"
    except DockerError as e:
        return False, str(e)


# ── Config Parsing ──────────────────────────────────────────────────


def list_active_configs() -> list[dict]:
    """Parse semua config files di conf.d/ dan extract informasi domain.

    Returns:
        List of dicts dengan keys: domain, target, config_file, has_ssl.
    """
    configs = []

    if not NGINX_CONF_DIR.exists():
        return configs

    for conf_file in sorted(NGINX_CONF_DIR.glob("*.conf")):
        if conf_file.name.startswith(("00-", "_", "default")):
            continue

        content = conf_file.read_text()

        # Extract server_name
        server_names = re.findall(r"server_name\s+([^;]+);", content)
        domain = conf_file.stem  # Filename tanpa .conf

        # Extract proxy_pass target
        proxy_targets = re.findall(r"proxy_pass\s+http://([^;]+);", content)
        target = proxy_targets[0].strip() if proxy_targets else "-"

        # Cek apakah config punya SSL & domain sertifikatnya
        has_ssl = "ssl_certificate" in content
        cert_domain_matches = re.findall(r"ssl_certificate\s+/etc/letsencrypt/live/([^/]+)/fullchain\.pem;", content)
        cert_domain = cert_domain_matches[0] if cert_domain_matches else domain

        # Collect server_name values
        all_names = set()
        for sn in server_names:
            for name in sn.strip().split():
                if name and name != "_":
                    all_names.add(name)

        configs.append({
            "domain": domain,
            "server_names": sorted(all_names),
            "target": target,
            "config_file": conf_file.name,
            "has_ssl": has_ssl,
            "cert_domain": cert_domain,
        })

    return configs
