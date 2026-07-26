"""Certbot helper — request, renew, dan manage SSL certificates."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.console import Console

from nginx_proxy_helper.config import (
    CERTBOT_CONF_DIR,
    CERTBOT_STAGING,
    DEFAULT_EMAIL,
)
from nginx_proxy_helper.lib.docker import run_certbot_docker, DockerError

console = Console()


class CertbotError(Exception):
    """Error saat operasi certbot."""
    pass


# ── Certificate Status ─────────────────────────────────────────────


def cert_dir(domain: str) -> Path:
    """Dapatkan path directory sertifikat untuk domain."""
    return CERTBOT_CONF_DIR / "live" / domain


def cert_exists(domain: str) -> bool:
    """Cek apakah sertifikat untuk domain sudah ada."""
    d = cert_dir(domain)
    return (d / "fullchain.pem").exists() and (d / "privkey.pem").exists()


def get_cert_expiry(domain: str) -> Optional[datetime]:
    """Baca expiry date dari sertifikat.

    Menggunakan openssl via python untuk membaca cert file.

    Args:
        domain: Domain name.

    Returns:
        Expiry datetime, atau None jika cert tidak ada.
    """
    cert_path = cert_dir(domain) / "fullchain.pem"
    if not cert_path.exists():
        return None

    try:
        import ssl
        cert = ssl.PEM_cert_to_DER_cert(
            cert_path.read_text().split("-----END CERTIFICATE-----")[0]
            + "-----END CERTIFICATE-----"
        )
        # Decode ASN.1 to get expiry — kita pakai cara sederhana via openssl subprocess
        from nginx_proxy_helper.lib.docker import run_command
        result = run_command(
            ["openssl", "x509", "-enddate", "-noout", "-in", str(cert_path)],
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            date_str = result.stdout.strip().split("=", 1)[1]
            parsed_dt = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
            return parsed_dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass

    return None


def get_cert_status(domain: str) -> str:
    """Dapatkan status sertifikat sebagai string yang readable.

    Args:
        domain: Domain name.

    Returns:
        Status string: "Valid (XX days)", "Expiring soon (XX days)", "Expired", atau "No certificate".
    """
    if not cert_exists(domain):
        return "❌ No certificate"

    expiry = get_cert_expiry(domain)
    if expiry is None:
        return "⚠️  Certificate exists (expiry unknown)"

    now = datetime.now(tz=timezone.utc)
    days_left = (expiry - now).days

    if days_left < 0:
        return f"🔴 Expired ({abs(days_left)} days ago)"
    elif days_left <= 30:
        return f"🟡 Expiring soon ({days_left} days left)"
    else:
        return f"🟢 Valid ({days_left} days left)"


# ── Certificate Request ────────────────────────────────────────────


def request_certificate(
    domain: str,
    www: bool = False,
    email: Optional[str] = None,
) -> bool:
    """Request SSL certificate via certbot certonly.

    Args:
        domain: Domain utama.
        www: Jika True, tambahkan www.domain.
        email: Email untuk Let's Encrypt. Pakai DEFAULT_EMAIL jika tidak diset.

    Returns:
        True jika berhasil.

    Raises:
        CertbotError: Jika certbot gagal.
    """
    email = email or DEFAULT_EMAIL

    args = [
        "certonly",
        "--webroot",
        "--webroot-path=/var/www/certbot",
        "--non-interactive",
        "--agree-tos",
        "-d", domain,
    ]

    if www:
        args.extend(["-d", f"www.{domain}"])

    if email:
        args.extend(["--email", email])
    else:
        args.append("--register-unsafely-without-email")

    if CERTBOT_STAGING:
        args.append("--staging")

    console.print(f"\n[yellow]Requesting SSL certificate for {domain}...[/yellow]")
    console.print(f"[dim]certbot {' '.join(args)}[/dim]\n")

    result = run_certbot_docker(args)

    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise CertbotError(
            f"Certbot gagal request certificate:\n{output}"
        )

    console.print(f"[green]✓[/green] SSL certificate obtained for {domain}")
    return True


def request_subdomain_certificate(
    subdomain: str,
    reuse_parent: bool = True,
    email: Optional[str] = None,
) -> str:
    """Request SSL certificate untuk subdomain.

    Args:
        subdomain: Subdomain (e.g., "api.example.com").
        reuse_parent: Jika True, expand parent domain cert. Jika False, request cert terpisah.
        email: Email untuk Let's Encrypt.

    Returns:
        cert_domain — domain name yang dipakai untuk path sertifikat.

    Raises:
        CertbotError: Jika certbot gagal.
    """
    from nginx_proxy_helper.lib.dns import get_parent_domain

    parent = get_parent_domain(subdomain)
    email = email or DEFAULT_EMAIL

    if reuse_parent and parent and cert_exists(parent):
        # Expand sertifikat parent domain
        console.print(
            f"[yellow]Expanding parent certificate ({parent}) "
            f"to include {subdomain}...[/yellow]"
        )

        args = [
            "certonly",
            "--webroot",
            "--webroot-path=/var/www/certbot",
            "--non-interactive",
            "--agree-tos",
            "--expand",
            "-d", parent,
            "-d", subdomain,
        ]

        # Cek apakah www.parent juga ada di cert sebelumnya
        www_parent_cert = cert_dir(parent) / "fullchain.pem"
        if (CERTBOT_CONF_DIR / "live" / parent).exists():
            # Tambahkan www jika sebelumnya ada
            renewal_conf = CERTBOT_CONF_DIR / "renewal" / f"{parent}.conf"
            if renewal_conf.exists():
                renewal_content = renewal_conf.read_text()
                if f"www.{parent}" in renewal_content:
                    args.extend(["-d", f"www.{parent}"])

        if email:
            args.extend(["--email", email])
        else:
            args.append("--register-unsafely-without-email")

        if CERTBOT_STAGING:
            args.append("--staging")

        console.print(f"[dim]certbot {' '.join(args)}[/dim]\n")

        result = run_certbot_docker(args)

        if result.returncode != 0:
            output = (result.stderr or result.stdout or "").strip()
            raise CertbotError(
                f"Certbot gagal expand certificate:\n{output}\n\n"
                f"Coba jalankan dengan --separate-cert untuk request cert terpisah."
            )

        console.print(f"[green]✓[/green] Certificate expanded to include {subdomain}")
        return parent  # cert_domain = parent

    else:
        # Request sertifikat terpisah untuk subdomain
        if reuse_parent and parent:
            console.print(
                f"[dim]Parent cert ({parent}) tidak ditemukan, "
                f"requesting separate certificate...[/dim]"
            )

        console.print(
            f"[yellow]Requesting separate SSL certificate for {subdomain}...[/yellow]"
        )

        args = [
            "certonly",
            "--webroot",
            "--webroot-path=/var/www/certbot",
            "--non-interactive",
            "--agree-tos",
            "-d", subdomain,
        ]

        if email:
            args.extend(["--email", email])
        else:
            args.append("--register-unsafely-without-email")

        if CERTBOT_STAGING:
            args.append("--staging")

        console.print(f"[dim]certbot {' '.join(args)}[/dim]\n")

        result = run_certbot_docker(args)

        if result.returncode != 0:
            output = (result.stderr or result.stdout or "").strip()
            raise CertbotError(
                f"Certbot gagal request certificate:\n{output}"
            )

        console.print(f"[green]✓[/green] SSL certificate obtained for {subdomain}")
        return subdomain  # cert_domain = subdomain


# ── Certificate Renewal ────────────────────────────────────────────


def renew_certificates() -> tuple[bool, str]:
    """Jalankan certbot renew untuk semua certificate.

    Returns:
        Tuple of (success, output_message).
    """
    console.print("[yellow]Renewing SSL certificates...[/yellow]")

    result = run_certbot_docker(["renew"])

    output = (result.stdout or "") + (result.stderr or "")
    success = result.returncode == 0

    if success:
        console.print("[green]✓[/green] Certificate renewal completed")
    else:
        console.print(f"[red]✗[/red] Certificate renewal failed")

    return success, output.strip()


# ── Certificate Removal ────────────────────────────────────────────


def remove_certificate(domain: str) -> bool:
    """Hapus sertifikat untuk domain via certbot.

    Args:
        domain: Domain name.

    Returns:
        True jika berhasil dihapus.
    """
    if not cert_exists(domain):
        console.print(f"[dim]No certificate found for {domain}[/dim]")
        return False

    result = run_certbot_docker([
        "delete",
        "--non-interactive",
        "--cert-name", domain,
    ])

    if result.returncode == 0:
        console.print(f"[green]✓[/green] Certificate removed for {domain}")
        return True
    else:
        output = (result.stderr or result.stdout or "").strip()
        console.print(f"[red]✗[/red] Failed to remove certificate: {output}")
        return False
