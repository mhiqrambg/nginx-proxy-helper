"""Package checker — validasi semua dependency yang dibutuhkan."""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Optional

from rich.console import Console
from rich.table import Table

console = Console()


def _check_command(cmd: str, version_flag: str = "--version") -> tuple[bool, str]:
    """Cek apakah command tersedia dan dapatkan versinya.

    Args:
        cmd: Command name (e.g., "docker").
        version_flag: Flag untuk mendapatkan versi.

    Returns:
        Tuple of (available, version_string).
    """
    path = shutil.which(cmd)
    if not path:
        return False, "Not installed"

    try:
        result = subprocess.run(
            [cmd, version_flag],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (result.stdout or result.stderr or "").strip()
        # Ambil baris pertama saja
        version = output.split("\n")[0] if output else "Unknown version"
        return True, version
    except Exception:
        return True, "Installed (version unknown)"


def _check_docker_compose() -> tuple[bool, str]:
    """Cek docker compose (v2 plugin style)."""
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            output = (result.stdout or "").strip()
            return True, output.split("\n")[0] if output else "Available"
        return False, "Not available"
    except Exception:
        return False, "Not available"


def _check_docker_running() -> tuple[bool, str]:
    """Cek apakah Docker daemon sedang berjalan."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, "Running"
        return False, "Not running"
    except Exception:
        return False, "Cannot connect"


def _check_python_package(package: str) -> tuple[bool, str]:
    """Cek apakah Python package terinstall.

    Args:
        package: Nama package (import name).

    Returns:
        Tuple of (installed, version_string).
    """
    try:
        mod = __import__(package)
        version = getattr(mod, "__version__", getattr(mod, "version", "unknown"))
        if callable(version):
            version = "installed"
        return True, str(version)
    except ImportError:
        return False, "Not installed"


def _check_network_exists(network: str = "nginx-network") -> tuple[bool, str]:
    """Cek apakah Docker network sudah ada."""
    try:
        result = subprocess.run(
            ["docker", "network", "inspect", network],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, "Exists"
        return False, "Not found"
    except Exception:
        return False, "Cannot check"


def _check_container_running(name: str) -> tuple[bool, str]:
    """Cek apakah container sedang berjalan."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            status = result.stdout.strip()
            is_running = status == "running"
            return is_running, status.capitalize()
        return False, "Not found"
    except Exception:
        return False, "Cannot check"


def run_full_check() -> bool:
    """Jalankan full dependency check dan tampilkan hasilnya.

    Returns:
        True jika semua critical dependency terpenuhi.
    """
    all_ok = True

    # ── System Dependencies ─────────────────────────────────────
    console.print("\n[bold]🔍 System Dependencies[/bold]\n")

    sys_table = Table()
    sys_table.add_column("Component", style="white", min_width=20)
    sys_table.add_column("Status", style="white", justify="center", min_width=8)
    sys_table.add_column("Details", style="dim")
    sys_table.add_column("Required", style="dim", justify="center")

    system_checks = [
        ("Python", "python3", True),
        ("Docker", "docker", True),
        ("OpenSSL", "openssl", False),
        ("curl", "curl", False),
    ]

    for name, cmd, required in system_checks:
        ok, detail = _check_command(cmd)
        icon = "✅" if ok else ("❌" if required else "⚠️")
        req_label = "Yes" if required else "No"

        if not ok and required:
            all_ok = False

        sys_table.add_row(name, icon, detail, req_label)

    # Docker Compose (special check)
    ok, detail = _check_docker_compose()
    icon = "✅" if ok else "❌"
    if not ok:
        all_ok = False
    sys_table.add_row("Docker Compose", icon, detail, "Yes")

    console.print(sys_table)

    # ── Docker Status ───────────────────────────────────────────
    console.print("\n[bold]🐳 Docker Status[/bold]\n")

    docker_table = Table()
    docker_table.add_column("Component", style="white", min_width=20)
    docker_table.add_column("Status", style="white", justify="center", min_width=8)
    docker_table.add_column("Details", style="dim")

    # Docker daemon
    ok, detail = _check_docker_running()
    icon = "✅" if ok else "❌"
    if not ok:
        all_ok = False
    docker_table.add_row("Docker Daemon", icon, detail)

    # Network
    ok, detail = _check_network_exists()
    icon = "✅" if ok else "⚠️"
    docker_table.add_row("nginx-network", icon, detail)

    # Containers
    for container in ["nginx", "certbot"]:
        ok, detail = _check_container_running(container)
        icon = "✅" if ok else "⚠️"
        docker_table.add_row(f"Container: {container}", icon, detail)

    console.print(docker_table)

    # ── Python Packages ─────────────────────────────────────────
    console.print("\n[bold]🐍 Python Packages[/bold]\n")

    pkg_table = Table()
    pkg_table.add_column("Package", style="white", min_width=20)
    pkg_table.add_column("Status", style="white", justify="center", min_width=8)
    pkg_table.add_column("Version", style="dim")

    packages = [
        ("click", "click"),
        ("Jinja2", "jinja2"),
        ("dnspython", "dns"),
        ("rich", "rich"),
        ("tabulate", "tabulate"),
    ]

    for display_name, import_name in packages:
        ok, version = _check_python_package(import_name)
        icon = "✅" if ok else "❌"
        if not ok:
            all_ok = False
        pkg_table.add_row(display_name, icon, version)

    console.print(pkg_table)

    # ── Summary ─────────────────────────────────────────────────
    console.print()
    if all_ok:
        console.print("[bold green]✅ All critical dependencies are satisfied![/bold green]\n")
    else:
        console.print("[bold red]❌ Some critical dependencies are missing.[/bold red]")
        console.print("[dim]Install missing dependencies and try again.[/dim]\n")

    return all_ok
