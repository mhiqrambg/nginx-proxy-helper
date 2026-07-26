"""DNS helper — domain resolution and A record validation."""

from __future__ import annotations

import socket
import urllib.request
from typing import Optional

import dns.resolver
import dns.exception
from rich.console import Console
from rich.table import Table

console = Console()


class DNSError(Exception):
    """Exception raised for DNS errors."""
    pass


def get_public_ip() -> str:
    """Get public IP address of the current machine/VPS.

    Tries multiple external IP resolution services in sequence.

    Returns:
        Public IP address as string.

    Raises:
        DNSError: If unable to retrieve public IP.
    """
    services = [
        "https://ifconfig.me/ip",
        "https://api.ipify.org",
        "https://icanhazip.com",
        "https://checkip.amazonaws.com",
    ]

    for url in services:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                ip = resp.read().decode("utf-8").strip()
                if ip and _is_valid_ip(ip):
                    return ip
        except Exception:
            continue

    raise DNSError(
        "Failed to retrieve VPS public IP address. "
        "Ensure your VPS is connected to the internet."
    )


def _is_valid_ip(ip: str) -> bool:
    """Validate if a string is a valid IP address."""
    try:
        socket.inet_aton(ip)
        return True
    except socket.error:
        return False


def resolve_domain(domain: str) -> list[str]:
    """Resolve A records for a domain.

    Args:
        domain: Domain name to resolve.

    Returns:
        List of resolved IP addresses.

    Raises:
        DNSError: If domain resolution fails.
    """
    try:
        answers = dns.resolver.resolve(domain, "A")
        return [rdata.address for rdata in answers]
    except dns.resolver.NXDOMAIN:
        raise DNSError(f"Domain '{domain}' not found (NXDOMAIN)")
    except dns.resolver.NoAnswer:
        raise DNSError(f"Domain '{domain}' has no A records")
    except dns.resolver.NoNameservers:
        raise DNSError(f"No nameservers available to answer for '{domain}'")
    except dns.exception.Timeout:
        raise DNSError(f"DNS resolution timed out for '{domain}'")
    except Exception as e:
        raise DNSError(f"DNS resolution failed for '{domain}': {e}")


def check_domain_points_to_vps(domain: str) -> tuple[bool, str, list[str]]:
    """Check if a domain's A record points to this VPS's public IP.

    Args:
        domain: Domain name to check.

    Returns:
        Tuple of (is_match, vps_ip, resolved_ips).

    Raises:
        DNSError: If resolution or public IP check fails.
    """
    vps_ip = get_public_ip()
    resolved_ips = resolve_domain(domain)
    match = vps_ip in resolved_ips
    return match, vps_ip, resolved_ips


def print_dns_check_result(
    domain: str,
    match: bool,
    vps_ip: str,
    resolved_ips: list[str],
) -> None:
    """Display DNS check results in a formatted Rich table.

    Args:
        domain: Domain name checked.
        match: Whether DNS points to VPS IP.
        vps_ip: Current VPS public IP.
        resolved_ips: List of resolved IP addresses.
    """
    console.print()

    table = Table(title=f"DNS Resolution: {domain}")
    table.add_column("Type", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Value", style="green" if match else "red")
    table.add_column("Status", style="bold")

    for ip in resolved_ips:
        status = "✅ Match" if ip == vps_ip else "❌ Mismatch"
        table.add_row("A", domain, ip, status)

    console.print(table)
    console.print(f"\n[dim]VPS Public IP: {vps_ip}[/dim]")

    if match:
        console.print(f"\n[green]✓ Domain '{domain}' successfully points to this VPS![/green]")
    else:
        console.print(f"\n[red]✗ Domain '{domain}' DOES NOT point to this VPS IP address![/red]")
        print_dns_instructions(domain, vps_ip)


def print_dns_instructions(domain: str, vps_ip: str) -> None:
    """Display DNS record configuration instructions.

    Args:
        domain: Target domain.
        vps_ip: Target VPS IP.
    """
    console.print("\n[bold yellow]Please add the following DNS A record at your domain registrar:[/bold yellow]\n")

    table = Table()
    table.add_column("Type", style="cyan", justify="center")
    table.add_column("Name / Host", style="white")
    table.add_column("Value", style="green")
    table.add_column("TTL", style="dim")

    parts = domain.split(".")
    if len(parts) > 2:
        name = ".".join(parts[:-2])
    else:
        name = "@"

    table.add_row("A", name, vps_ip, "3600")

    console.print(table)
    console.print(
        "\n[dim]After adding the record, wait for DNS propagation (typically 5-30 minutes),\n"
        "then run this command again.[/dim]"
    )


def get_parent_domain(subdomain: str) -> Optional[str]:
    """Extract parent domain from a subdomain string.

    Args:
        subdomain: e.g., "api.example.com"

    Returns:
        Parent domain string e.g. "example.com", or None if not a subdomain.
    """
    parts = subdomain.split(".")
    if len(parts) > 2:
        return ".".join(parts[-2:])
    return None


def is_subdomain(domain: str) -> bool:
    """Check if domain is a subdomain (has > 2 labels)."""
    return len(domain.split(".")) > 2
