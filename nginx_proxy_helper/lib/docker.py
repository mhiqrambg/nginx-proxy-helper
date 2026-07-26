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


def check_target_network_status(target: str) -> None:
    """Cek apakah target container terhubung ke network 'nginx-network'.

    Jika target adalah container:
      - Otomatis menghubungkan container ke 'nginx-network' jika belum terhubung.

    Jika target menggunakan host.docker.internal/localhost:
      - Mencari container yang cocok dan memberikan saran optimasi.

    Args:
        target: Target proxy string (e.g. "9router:20128", "host.docker.internal:20128").
    """
    if ":" not in target:
        return

    parts = target.split(":", 1)
    host, port = parts[0].strip(), parts[1].strip()

    # Case 1: Target adalah container name (misal: "9router")
    if host not in ("host.docker.internal", "localhost", "127.0.0.1", "0.0.0.0"):
        res = run_command(["docker", "inspect", "-f", "{{.State.Running}}", host], check=False)
        if res.returncode == 0:
            # Container ditemukan! Cek koneksi ke nginx-network
            net_check = run_command(
                ["docker", "inspect", "-f", f"{{{{index .NetworkSettings.Networks \"{DOCKER_NETWORK}\"}}}}", host],
                check=False,
            )
            is_connected = net_check.returncode == 0 and "<no value>" not in net_check.stdout

            if not is_connected:
                console.print(
                    f"[yellow]⚠ Container '{host}' belum terhubung ke network '{DOCKER_NETWORK}'.[/yellow]\n"
                    f"[cyan]⚡ Menghubungkan '{host}' ke '{DOCKER_NETWORK}' secara otomatis...[/cyan]"
                )
                conn_res = run_command(["docker", "network", "connect", DOCKER_NETWORK, host], check=False)
                if conn_res.returncode == 0:
                    console.print(f"[green]✓[/green] Container '{host}' berhasil dihubungkan ke '{DOCKER_NETWORK}'!")
                else:
                    raise DockerError(
                        f"Target container '{host}' ada tetapi gagal dihubungkan ke network '{DOCKER_NETWORK}'.\n"
                        f"Solusi manual: docker network connect {DOCKER_NETWORK} {host}"
                    )
            else:
                console.print(f"[green]✓[/green] Target container '{host}' sudah terhubung ke '{DOCKER_NETWORK}'")
            return
        else:
            # Container tidak ditemukan
            raise DockerError(
                f"Target container '{host}' tidak ditemukan atau tidak sedang berjalan.\n\n"
                f"💡 Solution & Troubleshooting:\n"
                f"  1. Pastikan nama container benar (cek via 'docker ps').\n"
                f"  2. Jika container ada, hubungkan ke network:\n"
                f"     docker network connect {DOCKER_NETWORK} {host}\n"
                f"  3. Atau jika service berjalan langsung di VPS host, gunakan:\n"
                f"     --target host.docker.internal:{port}"
            )

    # Case 2: Target menggunakan host.docker.internal / localhost
    ps_res = run_command(["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"], check=False)
    if ps_res.returncode == 0 and ps_res.stdout:
        found_containers = []
        for line in ps_res.stdout.strip().split("\n"):
            sp = line.split("\t")
            if len(sp) >= 2:
                c_name, c_ports = sp[0], sp[1]
                if port in c_ports and c_name not in (NGINX_CONTAINER_NAME, "certbot"):
                    found_containers.append((c_name, c_ports))

        if found_containers:
            console.print(f"\n[bold yellow]💡 Smart Target Suggestion:[/bold yellow]")
            for c_name, c_ports in found_containers:
                net_check = run_command(
                    ["docker", "inspect", "-f", f"{{{{index .NetworkSettings.Networks \"{DOCKER_NETWORK}\"}}}}", c_name],
                    check=False,
                )
                is_connected = net_check.returncode == 0 and "<no value>" not in net_check.stdout

                if not is_connected:
                    console.print(
                        f"  Ditemukan container [cyan]'{c_name}'[/cyan] dengan port {port}.\n"
                        f"  [yellow]Rekomendasi:[/yellow] Hubungkan ke network agar proxy lancar:\n"
                        f"    1. [white]docker network connect {DOCKER_NETWORK} {c_name}[/white]\n"
                        f"    2. Gunakan target: [green]--target {c_name}:{port}[/green]"
                    )
                else:
                    console.print(
                        f"  Container [cyan]'{c_name}'[/cyan] terdeteksi di '{DOCKER_NETWORK}'.\n"
                        f"  [green]Rekomendasi:[/green] Gunakan target container internal: [green]--target {c_name}:{port}[/green]"
                    )

