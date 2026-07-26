"""Installer module — auto-install Docker & Docker Compose, setup network & launch containers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from rich.console import Console
from rich.panel import Panel

from nginx_proxy_helper.config import COMPOSE_DIR, DOCKER_NETWORK
from nginx_proxy_helper.lib.docker import (
    docker_compose_up,
    ensure_network_exists,
    is_container_running,
    run_command,
)

console = Console()


def is_docker_installed() -> bool:
    """Check if docker executable is available."""
    return shutil.which("docker") is not None


def is_docker_compose_available() -> bool:
    """Check if docker compose v2 plugin is available."""
    try:
        res = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
        return res.returncode == 0
    except Exception:
        return False


def install_docker() -> bool:
    """Auto-install Docker & Docker Compose plugin on Linux using official get.docker.com script.

    Returns:
        True if installation succeeded.
    """
    console.print("\n[bold yellow]📦 Docker / Docker Compose not found.[/bold yellow]")
    console.print("[yellow]Installing Docker & Docker Compose via official script (get.docker.com)...[/yellow]\n")

    if sys.platform not in ("linux", "linux2"):
        console.print(
            "[red]✗ Automated Docker installation is supported on Linux only (Ubuntu/Debian/CentOS/RHEL/Arch).[/red]\n"
            "[dim]On macOS/Windows, please install Docker Desktop manually.[/dim]"
        )
        return False

    try:
        # Run get.docker.com script
        cmd = "curl -fsSL https://get.docker.com | sh"
        if os.geteuid() != 0:
            if shutil.which("sudo"):
                cmd = f"sudo {cmd}"
            else:
                console.print("[red]✗ Root / sudo permissions required to install Docker.[/red]")
                return False

        console.print(f"[dim]Executing: {cmd}[/dim]\n")
        res = subprocess.run(cmd, shell=True)

        if res.returncode != 0:
            console.print("[red]✗ Failed to install Docker.[/red]")
            return False

        # Start and enable docker service
        if shutil.which("systemctl"):
            subprocess.run(["sudo", "systemctl", "enable", "--now", "docker"], check=False)

        console.print("[green]✓[/green] Docker & Docker Compose successfully installed!")
        return True

    except Exception as e:
        console.print(f"[red]✗ Error installing Docker: {e}[/red]")
        return False


def setup_vps_environment() -> bool:
    """Run automated VPS setup:
    1. Check/Install Docker & Docker Compose
    2. Ensure Docker daemon is running
    3. Create nginx-network
    4. Start Nginx & Certbot containers
    """
    console.print(Panel(
        "[bold]🛠️ nginx-proxy-helper — VPS Environment Setup[/bold]",
        border_style="blue",
    ))

    # 1. Check & Install Docker
    if not is_docker_installed() or not is_docker_compose_available():
        if not install_docker():
            return False
    else:
        console.print("[green]✓[/green] Docker & Docker Compose are already installed.")

    # 2. Check Docker daemon running
    try:
        run_command(["docker", "info"], check=True)
        console.print("[green]✓[/green] Docker daemon is running.")
    except Exception:
        console.print("[yellow]Docker daemon is not running. Starting service...[/yellow]")
        try:
            if shutil.which("systemctl"):
                cmd = ["sudo", "systemctl", "start", "docker"] if os.geteuid() != 0 else ["systemctl", "start", "docker"]
                subprocess.run(cmd, check=True)
                console.print("[green]✓[/green] Docker daemon successfully started.")
            else:
                console.print("[red]✗ Unable to start Docker daemon automatically.[/red]")
                return False
        except Exception as e:
            console.print(f"[red]✗ Failed to start Docker daemon: {e}[/red]")
            return False

    # 3. Create Docker Network
    console.print(f"\n[bold]Checking Docker Network '{DOCKER_NETWORK}'...[/bold]")
    try:
        ensure_network_exists()
    except Exception as e:
        console.print(f"[red]✗ Failed to create Docker network: {e}[/red]")
        return False

    # 4. Start Docker Compose Services
    console.print("\n[bold]Starting Nginx & Certbot containers...[/bold]")
    try:
        docker_compose_up()
        if is_container_running("nginx"):
            console.print("[bold green]✅ Setup complete! Nginx & Certbot containers are active.[/bold green]\n")
            return True
        else:
            console.print("[yellow]⚠ Docker Compose containers are not running yet. Check docker logs.[/yellow]\n")
            return False
    except Exception as e:
        console.print(f"[red]✗ Error starting docker compose services: {e}[/red]")
        return False
