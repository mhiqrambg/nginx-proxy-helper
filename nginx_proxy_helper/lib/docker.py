"""Docker helper — menjalankan docker exec dan docker compose commands."""

from __future__ import annotations

import subprocess
import sys
from typing import Optional

from rich.console import Console

from nginx_proxy_helper.config import (
    COMPOSE_DIR,
    DOCKER_NETWORK,
    NGINX_CONTAINER_NAME,
)

console = Console()


class DockerError(Exception):
    """Error saat menjalankan docker command."""
    pass


def run_command(
    cmd: list[str],
    cwd: Optional[str] = None,
    capture: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Jalankan shell command dengan error handling.

    Args:
        cmd: Command dan arguments sebagai list.
        cwd: Working directory.
        capture: Capture stdout/stderr atau tampilkan langsung.
        check: Raise exception jika return code != 0.

    Returns:
        CompletedProcess result.

    Raises:
        DockerError: Jika command gagal dan check=True.
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=capture,
            text=True,
            timeout=120,
        )
        if check and result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else ""
            stdout = result.stdout.strip() if result.stdout else ""
            msg = stderr or stdout or f"Command failed with exit code {result.returncode}"
            raise DockerError(msg)
        return result
    except FileNotFoundError:
        raise DockerError(
            f"Command tidak ditemukan: {cmd[0]}. "
            f"Pastikan docker sudah terinstall."
        )
    except subprocess.TimeoutExpired:
        raise DockerError(f"Command timeout setelah 120 detik: {' '.join(cmd)}")


def ensure_network_exists() -> None:
    """Buat docker network 'nginx-network' jika belum ada."""
    result = run_command(
        ["docker", "network", "ls", "--format", "{{.Name}}"],
        check=False,
    )
    existing = result.stdout.strip().split("\n") if result.stdout else []

    if DOCKER_NETWORK not in existing:
        console.print(f"[yellow]Creating docker network '{DOCKER_NETWORK}'...[/yellow]")
        run_command(["docker", "network", "create", DOCKER_NETWORK])
        console.print(f"[green]✓[/green] Network '{DOCKER_NETWORK}' created")
    else:
        console.print(f"[dim]Network '{DOCKER_NETWORK}' already exists[/dim]")


def docker_exec(container: str, command: str) -> subprocess.CompletedProcess:
    """Jalankan command di dalam docker container.

    Args:
        container: Nama container.
        command: Command string yang akan dijalankan.

    Returns:
        CompletedProcess result.
    """
    return run_command(
        ["docker", "exec", container] + command.split(),
    )


def docker_compose_up() -> None:
    """Start docker compose services."""
    console.print("[yellow]Starting docker compose services...[/yellow]")
    run_command(
        ["docker", "compose", "up", "-d"],
        cwd=str(COMPOSE_DIR),
    )
    console.print("[green]✓[/green] Docker compose services started")


def docker_compose_down() -> None:
    """Stop docker compose services."""
    run_command(
        ["docker", "compose", "down"],
        cwd=str(COMPOSE_DIR),
    )


def is_container_running(container: str = NGINX_CONTAINER_NAME) -> bool:
    """Cek apakah container sedang berjalan."""
    result = run_command(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def ensure_nginx_running() -> None:
    """Pastikan nginx container sedang berjalan, start jika belum.

    Raises:
        DockerError: Jika tidak bisa start nginx.
    """
    if not is_container_running():
        console.print("[yellow]Nginx container not running. Starting...[/yellow]")
        ensure_network_exists()
        docker_compose_up()

        if not is_container_running():
            raise DockerError(
                "Gagal start nginx container. "
                "Cek docker compose logs untuk detail."
            )


def run_certbot_docker(args: list[str]) -> subprocess.CompletedProcess:
    """Jalankan certbot via docker run (one-shot container).

    Args:
        args: Arguments untuk certbot command.

    Returns:
        CompletedProcess result.
    """
    cmd = [
        "docker", "compose", "run", "--rm",
        "--entrypoint", "certbot",
        "certbot",
    ] + args

    return run_command(cmd, cwd=str(COMPOSE_DIR), check=False)
