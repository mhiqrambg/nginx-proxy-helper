"""Docker helper — docker exec, compose, and container network operations."""

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
    """Exception raised for Docker execution errors."""
    pass


def run_command(
    cmd: list[str],
    cwd: Optional[str] = None,
    capture: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run shell command with error handling.

    Args:
        cmd: Command and arguments list.
        cwd: Working directory.
        capture: Capture stdout/stderr or display directly.
        check: Raise exception if return code != 0.

    Returns:
        CompletedProcess result.

    Raises:
        DockerError: If command fails and check=True.
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
            f"Command not found: {cmd[0]}. "
            f"Ensure Docker is installed and in your PATH."
        )
    except subprocess.TimeoutExpired:
        raise DockerError(f"Command timed out after 120 seconds: {' '.join(cmd)}")


def ensure_network_exists() -> None:
    """Create docker network 'nginx-network' if it does not exist."""
    result = run_command(
        ["docker", "network", "ls", "--format", "{{.Name}}"],
        check=False,
    )
    existing = result.stdout.strip().split("\n") if result.stdout else []

    if DOCKER_NETWORK not in existing:
        console.print(f"[yellow]Creating Docker network '{DOCKER_NETWORK}'...[/yellow]")
        run_command(["docker", "network", "create", DOCKER_NETWORK])
        console.print(f"[green]✓[/green] Network '{DOCKER_NETWORK}' created")
    else:
        console.print(f"[dim]Network '{DOCKER_NETWORK}' already exists[/dim]")


def docker_exec(container: str, command: str) -> subprocess.CompletedProcess:
    """Execute command inside a running Docker container.

    Args:
        container: Container name.
        command: Command string to execute.

    Returns:
        CompletedProcess result.
    """
    return run_command(
        ["docker", "exec", container] + command.split(),
    )


def docker_compose_up() -> None:
    """Start Docker Compose services."""
    console.print("[yellow]Starting Docker Compose services...[/yellow]")
    run_command(
        ["docker", "compose", "up", "-d"],
        cwd=str(COMPOSE_DIR),
    )
    console.print("[green]✓[/green] Docker Compose services started")


def docker_compose_down() -> None:
    """Stop Docker Compose services."""
    run_command(
        ["docker", "compose", "down"],
        cwd=str(COMPOSE_DIR),
    )


def is_container_running(container: str = NGINX_CONTAINER_NAME) -> bool:
    """Check if a container is currently running."""
    result = run_command(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def ensure_nginx_running() -> None:
    """Ensure Nginx container is running, start if stopped.

    Raises:
        DockerError: If unable to start Nginx container.
    """
    if not is_container_running():
        console.print("[yellow]Nginx container not running. Starting...[/yellow]")
        ensure_network_exists()
        docker_compose_up()

        if not is_container_running():
            raise DockerError(
                "Failed to start Nginx container. "
                "Check docker compose logs for details."
            )


def run_certbot_docker(args: list[str]) -> subprocess.CompletedProcess:
    """Run certbot via docker run (one-shot container).

    Args:
        args: Arguments for certbot command.

    Returns:
        CompletedProcess result.
    """
    cmd = [
        "docker", "compose", "run", "--rm",
        "--entrypoint", "certbot",
        "certbot",
    ] + args

    return run_command(cmd, cwd=str(COMPOSE_DIR), check=False)


def get_containers_in_network(network_name: str = DOCKER_NETWORK) -> set[str]:
    """Get set of container names connected to a Docker network."""
    res = run_command(
        ["docker", "network", "inspect", network_name, "--format", "{{range .Containers}}{{.Name}} {{end}}"],
        check=False,
    )
    if res.returncode == 0 and res.stdout:
        return set(res.stdout.strip().split())
    return set()


def check_target_network_status(target: str) -> None:
    """Check if target container is connected to 'nginx-network'.

    If target is a container:
      - Automatically connects container to 'nginx-network' if missing.

    If target uses host.docker.internal / localhost:
      - Searches for matching containers and provides smart recommendations.

    Args:
        target: Target proxy string (e.g. "9router:20128", "host.docker.internal:20128").
    """
    if ":" not in target:
        return

    parts = target.split(":", 1)
    host, port = parts[0].strip(), parts[1].strip()

    # Case 1: Target is a container name (e.g., "9router")
    if host not in ("host.docker.internal", "localhost", "127.0.0.1", "0.0.0.0"):
        res = run_command(["docker", "inspect", "-f", "{{.State.Running}}", host], check=False)
        if res.returncode == 0 and res.stdout.strip() == "true":
            # Container exists & running! Check network connection
            net_containers = get_containers_in_network(DOCKER_NETWORK)
            is_connected = host in net_containers

            if not is_connected:
                console.print(
                    f"\n[bold yellow]⚠ Warning: Target container '{host}' is not connected to '{DOCKER_NETWORK}'.[/bold yellow]\n"
                    f"[cyan]⚡ Attempting to connect '{host}' to '{DOCKER_NETWORK}' automatically...[/cyan]"
                )
                conn_res = run_command(["docker", "network", "connect", DOCKER_NETWORK, host], check=False)

                # Re-check after connect attempt
                if conn_res.returncode == 0 and host in get_containers_in_network(DOCKER_NETWORK):
                    console.print(f"[green]✓[/green] Container '{host}' successfully connected to '{DOCKER_NETWORK}'!")
                else:
                    raise DockerError(
                        f"Target container '{host}' is not connected to network '{DOCKER_NETWORK}'.\n\n"
                        f"💡 Solution:\n"
                        f"  Run this command on your VPS terminal:\n"
                        f"    docker network connect {DOCKER_NETWORK} {host}\n\n"
                        f"  Then re-run proxy add-domain."
                    )
            else:
                console.print(f"[green]✓[/green] Target container '{host}' verified on network '{DOCKER_NETWORK}'")
            return
        else:
            # Container not found or not running
            raise DockerError(
                f"Target container '{host}' not found or not currently running.\n\n"
                f"💡 Solution & Troubleshooting:\n"
                f"  1. Check running container names with: docker ps\n"
                f"  2. If container is running, connect it to the network:\n"
                f"     docker network connect {DOCKER_NETWORK} {host}\n"
                f"  3. Or if service runs directly on VPS host, use:\n"
                f"     --target host.docker.internal:{port}"
            )

    # Case 2: Target uses host.docker.internal / localhost
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
                net_containers = get_containers_in_network(DOCKER_NETWORK)
                is_connected = c_name in net_containers

                if not is_connected:
                    console.print(
                        f"  Found container [cyan]'{c_name}'[/cyan] matching port {port}.\n"
                        f"  [yellow]Recommendation:[/yellow] Connect to network for direct proxying:\n"
                        f"    1. [white]docker network connect {DOCKER_NETWORK} {c_name}[/white]\n"
                        f"    2. Use target: [green]--target {c_name}:{port}[/green]"
                    )
                else:
                    console.print(
                        f"  Container [cyan]'{c_name}'[/cyan] detected on '{DOCKER_NETWORK}'.\n"
                        f"  [green]Recommendation:[/green] Use container name as target: [green]--target {c_name}:{port}[/green]"
                    )
