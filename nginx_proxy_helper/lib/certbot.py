"""Certbot helper — request, renew, and manage SSL certificates."""

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
    """Exception raised for Certbot operations."""
    pass


# ── Certificate Status ─────────────────────────────────────────────


def cert_dir(domain: str) -> Path:
    """Get certificate directory path for domain."""
    return CERTBOT_CONF_DIR / "live" / domain


def cert_exists(domain: str) -> bool:
    """Check if SSL certificate files exist for domain."""
    d = cert_dir(domain)
    return (d / "fullchain.pem").exists() and (d / "privkey.pem").exists()


def get_cert_expiry(domain: str) -> Optional[datetime]:
    """Read certificate expiry datetime.

    Args:
        domain: Domain name.

    Returns:
        Expiry datetime (timezone-aware UTC), or None if cert does not exist.
    """
    cert_path = cert_dir(domain) / "fullchain.pem"
    if not cert_path.exists():
        return None

    try:
        from nginx_proxy_helper.lib.docker import run_command
        result = run_command(
            ["openssl", "x509", "-enddate", "-noout", "-in", str(cert_path)],
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            # Output format: notAfter=Jul 26 12:00:00 2026 GMT
            date_str = result.stdout.strip().split("=", 1)[1]
            parsed_dt = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
            return parsed_dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass

    return None


def get_cert_status(domain: str) -> str:
    """Get human-readable certificate status string.

    Args:
        domain: Domain name.

    Returns:
        Status string: "Valid (XX days left)", "Expiring soon (XX days left)", "Expired", or "No certificate".
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
        domain: Primary domain name.
        www: If True, include www.domain.
        email: Email address for Let's Encrypt notifications.

    Returns:
        True if successful.

    Raises:
        CertbotError: If certbot execution fails.
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
            f"Certbot failed to obtain SSL certificate:\n{output}"
        )

    console.print(f"[green]✓[/green] SSL certificate obtained for {domain}")
    return True


def request_subdomain_certificate(
    subdomain: str,
    reuse_parent: bool = True,
    email: Optional[str] = None,
) -> str:
    """Request SSL certificate for a subdomain.

    Args:
        subdomain: Subdomain name (e.g., "api.example.com").
        reuse_parent: If True, expand parent domain cert. If False, request separate cert.
        email: Email address for Let's Encrypt.

    Returns:
        cert_domain — domain name used for the certificate directory path.

    Raises:
        CertbotError: If certbot execution fails.
    """
    from nginx_proxy_helper.lib.dns import get_parent_domain

    parent = get_parent_domain(subdomain)
    email = email or DEFAULT_EMAIL

    if reuse_parent and parent and cert_exists(parent):
        # Expand parent domain certificate
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

        if (CERTBOT_CONF_DIR / "live" / parent).exists():
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
                f"Certbot failed to expand certificate:\n{output}\n\n"
                f"Try running with --separate-cert to request an isolated certificate."
            )

        console.print(f"[green]✓[/green] Certificate expanded to include {subdomain}")
        return parent  # cert_domain = parent

    else:
        # Request separate certificate for subdomain
        if reuse_parent and parent:
            console.print(
                f"[dim]Parent certificate ({parent}) not found. "
                f"Requesting separate certificate...[/dim]"
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
                f"Certbot failed to obtain SSL certificate:\n{output}"
            )

        console.print(f"[green]✓[/green] SSL certificate obtained for {subdomain}")
        return subdomain  # cert_domain = subdomain


# ── Certificate Renewal ────────────────────────────────────────────


def renew_certificates() -> tuple[bool, str]:
    """Run certbot renew for all certificates.

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
    """Remove certificate files for domain via certbot.

    Args:
        domain: Domain name.

    Returns:
        True if successfully removed.
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
