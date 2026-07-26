"""DNS helper — resolusi domain dan validasi A record."""

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
    """Error saat DNS lookup."""
    pass


def get_public_ip() -> str:
    """Dapatkan public IP dari VPS/machine saat ini.

    Mencoba beberapa service secara berurutan sebagai fallback.

    Returns:
        Public IP address sebagai string.

    Raises:
        DNSError: Jika gagal mendapatkan public IP.
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
        "Gagal mendapatkan public IP. "
        "Pastikan VPS terhubung ke internet."
    )


def _is_valid_ip(ip: str) -> bool:
    """Validasi apakah string adalah IP address yang valid."""
    try:
        socket.inet_aton(ip)
        return True
    except socket.error:
        return False


def resolve_domain(domain: str) -> list[str]:
    """Resolve A record dari domain.

    Args:
        domain: Domain name yang akan di-resolve.

    Returns:
        List of IP addresses yang di-resolve.

    Raises:
        DNSError: Jika domain tidak bisa di-resolve.
    """
    try:
        answers = dns.resolver.resolve(domain, "A")
        return [rdata.address for rdata in answers]
    except dns.resolver.NXDOMAIN:
        raise DNSError(f"Domain '{domain}' tidak ditemukan (NXDOMAIN)")
    except dns.resolver.NoAnswer:
        raise DNSError(f"Domain '{domain}' tidak punya A record")
    except dns.resolver.NoNameservers:
        raise DNSError(f"Tidak ada nameserver yang bisa menjawab untuk '{domain}'")
    except dns.exception.Timeout:
        raise DNSError(f"DNS lookup timeout untuk '{domain}'")
    except Exception as e:
        raise DNSError(f"DNS lookup gagal untuk '{domain}': {e}")


def check_domain_points_to_vps(domain: str) -> tuple[bool, str, list[str]]:
    """Cek apakah domain sudah mengarah ke IP VPS.

    Args:
        domain: Domain yang akan dicek.

    Returns:
        Tuple of (match, vps_ip, resolved_ips).

    Raises:
        DNSError: Jika gagal resolve atau gagal dapatkan VPS IP.
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
    """Tampilkan hasil DNS check dalam format yang informatif.

    Args:
        domain: Domain yang dicek.
        match: Apakah DNS match dengan VPS IP.
        vps_ip: IP VPS saat ini.
        resolved_ips: List IP yang di-resolve.
    """
    console.print()

    # Tabel hasil resolve saat ini
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
        console.print(f"\n[green]✓ Domain '{domain}' sudah mengarah ke VPS ini![/green]")
    else:
        console.print(f"\n[red]✗ Domain '{domain}' BELUM mengarah ke VPS ini![/red]")
        print_dns_instructions(domain, vps_ip)


def print_dns_instructions(domain: str, vps_ip: str) -> None:
    """Tampilkan instruksi DNS record yang perlu ditambahkan.

    Args:
        domain: Domain yang perlu disetup.
        vps_ip: IP VPS tujuan.
    """
    console.print("\n[bold yellow]Tambahkan DNS record berikut di domain registrar Anda:[/bold yellow]\n")

    table = Table()
    table.add_column("Type", style="cyan", justify="center")
    table.add_column("Name / Host", style="white")
    table.add_column("Value", style="green")
    table.add_column("TTL", style="dim")

    # Determine if this is a subdomain
    parts = domain.split(".")
    if len(parts) > 2:
        # Subdomain: e.g., api.example.com → Name = "api"
        name = ".".join(parts[:-2])
    else:
        # Root domain: e.g., example.com → Name = "@"
        name = "@"

    table.add_row("A", name, vps_ip, "3600")

    console.print(table)
    console.print(
        "\n[dim]Setelah menambahkan record, tunggu propagasi DNS (biasanya 5-30 menit).\n"
        "Kemudian jalankan ulang command ini.[/dim]"
    )


def get_parent_domain(subdomain: str) -> Optional[str]:
    """Extract parent domain dari subdomain.

    Args:
        subdomain: e.g., "api.example.com"

    Returns:
        Parent domain, e.g., "example.com", atau None jika bukan subdomain.
    """
    parts = subdomain.split(".")
    if len(parts) > 2:
        return ".".join(parts[-2:])
    return None


def is_subdomain(domain: str) -> bool:
    """Cek apakah domain adalah subdomain (punya > 2 parts)."""
    return len(domain.split(".")) > 2
