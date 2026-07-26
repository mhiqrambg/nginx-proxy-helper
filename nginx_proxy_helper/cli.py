"""CLI entrypoint — all proxy subcommands defined here."""

from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from nginx_proxy_helper import __version__
from nginx_proxy_helper.config import ensure_directories
from nginx_proxy_helper.lib.dns import (
    DNSError,
    check_domain_points_to_vps,
    get_parent_domain,
    is_subdomain,
    print_dns_check_result,
)
from nginx_proxy_helper.lib.docker import (
    DockerError,
    check_target_network_status,
    ensure_nginx_running,
)
from nginx_proxy_helper.lib.nginx import (
    backup_config,
    cleanup_old_backups,
    config_exists,
    export_standalone_setup,
    list_active_configs,
    reload_nginx,
    remove_config,
    render_http_challenge_config,
    render_ssl_config,
    restore_config,
    test_nginx_config,
    write_config,
)
from nginx_proxy_helper.lib.certbot import (
    CertbotError,
    cert_exists,
    get_cert_status,
    remove_certificate,
    renew_certificates,
    request_certificate,
    request_subdomain_certificate,
)

console = Console()


# ── CLI Group ───────────────────────────────────────────────────────


@click.group()
@click.version_option(version=__version__, prog_name="nginx-proxy-helper")
def cli():
    """🔧 nginx-proxy-helper — Manage Nginx reverse proxy + Let's Encrypt SSL on VPS."""
    ensure_directories()


# ── Command: add-domain ────────────────────────────────────────────


@cli.command("add-domain")
@click.argument("domain")
@click.option("--target", required=True, help="Target proxy address (e.g., app:3000)")
@click.option("--www", is_flag=True, default=False, help="Add www.domain as an alias")
@click.option("--email", default=None, help="Email address for Let's Encrypt notifications")
@click.option("--skip-dns-check", is_flag=True, default=False, help="Skip DNS validation")
@click.option("--force", is_flag=True, default=False, help="Overwrite existing configuration")
def add_domain(domain: str, target: str, www: bool, email: str, skip_dns_check: bool, force: bool):
    """Add a new main domain with reverse proxy + SSL certificate.

    Examples:
        proxy add-domain example.com --target app:3000 --www
        proxy add-domain example.com --target host.docker.internal:8080
    """
    console.print(Panel(
        f"[bold]Adding domain:[/bold] {domain}\n"
        f"[bold]Target:[/bold] {target}\n"
        f"[bold]WWW alias:[/bold] {'Yes' if www else 'No'}",
        title="🌐 Add Domain",
        border_style="blue",
    ))

    # Check if config exists
    if config_exists(domain) and not force:
        console.print(
            f"\n[red]✗ Configuration for '{domain}' already exists![/red]\n"
            f"[dim]Use --force to overwrite.[/dim]"
        )
        sys.exit(1)

    # Step 1: DNS Check
    if not skip_dns_check:
        console.print("\n[bold]Step 1/5:[/bold] Checking DNS records...")
        try:
            match, vps_ip, resolved_ips = check_domain_points_to_vps(domain)
            print_dns_check_result(domain, match, vps_ip, resolved_ips)

            if www:
                console.print(f"\nChecking www alias: www.{domain}...")
                try:
                    www_match, _, www_ips = check_domain_points_to_vps(f"www.{domain}")
                    if not www_match:
                        console.print(
                            f"[yellow]⚠️ Warning: www.{domain} does not point to this VPS IP![/yellow]"
                        )
                except DNSError:
                    console.print(
                        f"[yellow]⚠️ Warning: Failed to resolve www.{domain}[/yellow]"
                    )

            if not match:
                console.print(
                    "\n[red]✗ DNS check failed! Domain does not point to this VPS.[/red]\n"
                    "[dim]Add the DNS record first, or use --skip-dns-check if you're sure.[/dim]"
                )
                sys.exit(1)

        except DNSError as e:
            console.print(f"\n[red]✗ DNS Error: {e}[/red]")
            sys.exit(1)
    else:
        console.print("\n[bold]Step 1/5:[/bold] DNS check [yellow]SKIPPED[/yellow]")

    # Step 2: Ensure nginx is running
    console.print("\n[bold]Step 2/5:[/bold] Ensuring nginx is running & verifying target network...")
    try:
        ensure_nginx_running()
        check_target_network_status(target)
    except DockerError as e:
        console.print(f"\n[red]✗ Docker Error: {e}[/red]")
        sys.exit(1)

    # Step 3: Write HTTP-only config (for ACME challenge)
    console.print("\n[bold]Step 3/5:[/bold] Creating HTTP challenge config...")
    backup_path = backup_config(domain)  # Backup existing config if any

    try:
        http_config = render_http_challenge_config(domain, www)
        write_config(domain, http_config)

        # Reload nginx with HTTP config
        success, msg = reload_nginx()
        if not success:
            console.print(f"[red]✗ Nginx reload failed: {msg}[/red]")
            if backup_path:
                restore_config(domain, backup_path)
            else:
                remove_config(domain)
            sys.exit(1)

        console.print("[green]✓[/green] HTTP config active, ready for ACME challenge")
    except Exception as e:
        console.print(f"[red]✗ Error creating HTTP config: {e}[/red]")
        if backup_path:
            restore_config(domain, backup_path)
        sys.exit(1)

    # Step 4: Request SSL certificate
    console.print("\n[bold]Step 4/5:[/bold] Requesting SSL certificate via certbot...")
    try:
        request_certificate(domain, www=www, email=email)
    except (CertbotError, DockerError) as e:
        console.print(f"\n[red]✗ Certbot Error:[/red]\n{e}")
        console.print("\n[yellow]Rolling back: removing HTTP-only config...[/yellow]")
        if backup_path:
            restore_config(domain, backup_path)
        else:
            remove_config(domain)
        reload_nginx()
        sys.exit(1)

    # Step 5: Write final SSL config
    console.print("\n[bold]Step 5/5:[/bold] Applying final SSL config...")
    try:
        ssl_config = render_ssl_config(domain, target, www=www)
        write_config(domain, ssl_config)

        # Test nginx config before reload
        test_ok, test_msg = test_nginx_config()
        if not test_ok:
            console.print(f"[red]✗ Nginx config test failed: {test_msg}[/red]")
            console.print("[yellow]Rolling back to HTTP config...[/yellow]")
            if backup_path:
                restore_config(domain, backup_path)
            else:
                write_config(domain, http_config)
            reload_nginx()
            sys.exit(1)

        # Reload nginx with SSL config
        reload_ok, reload_msg = reload_nginx()
        if not reload_ok:
            console.print(f"[red]✗ Nginx reload failed: {reload_msg}[/red]")
            if backup_path:
                restore_config(domain, backup_path)
            sys.exit(1)

        cleanup_old_backups(domain)

    except Exception as e:
        console.print(f"[red]✗ Error applying SSL config: {e}[/red]")
        if backup_path:
            restore_config(domain, backup_path)
        sys.exit(1)

    # Success!
    console.print(Panel(
        f"[green]✓ Domain '{domain}' successfully configured![/green]\n\n"
        f"  🌐 http://{domain} → https://{domain}\n"
        f"  🔒 SSL Certificate Active\n"
        f"  🔄 Proxy target: {target}",
        title="✅ Success",
        border_style="green",
    ))


# ── Command: add-subdomain ─────────────────────────────────────────


@cli.command("add-subdomain")
@click.argument("subdomain")
@click.option("--target", required=True, help="Target proxy address (e.g., api-service:8080)")
@click.option("--separate-cert", is_flag=True, default=False,
              help="Request separate SSL cert instead of reusing parent domain cert")
@click.option("--email", default=None, help="Email address for Let's Encrypt notifications")
@click.option("--skip-dns-check", is_flag=True, default=False, help="Skip DNS validation")
@click.option("--force", is_flag=True, default=False, help="Overwrite existing configuration")
def add_subdomain(
    subdomain: str,
    target: str,
    separate_cert: bool,
    email: str,
    skip_dns_check: bool,
    force: bool,
):
    """Add a subdomain with reverse proxy + SSL.

    By default, attempts to reuse/expand parent domain certificate.

    Examples:
        proxy add-subdomain api.example.com --target api-service:8080
        proxy add-subdomain blog.example.com --target ghost:2368 --separate-cert
    """
    if not is_subdomain(subdomain):
        console.print(
            f"[red]✗ '{subdomain}' does not appear to be a subdomain![/red]\n"
            f"[dim]Use 'proxy add-domain' for main domains.[/dim]"
        )
        sys.exit(1)

    parent_domain = get_parent_domain(subdomain)
    reuse_cert = not separate_cert

    console.print(Panel(
        f"[bold]Adding subdomain:[/bold] {subdomain}\n"
        f"[bold]Target:[/bold] {target}\n"
        f"[bold]Parent domain:[/bold] {parent_domain or 'N/A'}\n"
        f"[bold]SSL Cert Mode:[/bold] {'Reuse Parent Cert' if reuse_cert else 'Separate Cert'}",
        title="🌐 Add Subdomain",
        border_style="blue",
    ))

    # Check if config exists
    if config_exists(subdomain) and not force:
        console.print(
            f"\n[red]✗ Configuration for '{subdomain}' already exists![/red]\n"
            f"[dim]Use --force to overwrite.[/dim]"
        )
        sys.exit(1)

    # Step 1: DNS Check
    if not skip_dns_check:
        console.print("\n[bold]Step 1/5:[/bold] Checking DNS records...")
        try:
            match, vps_ip, resolved_ips = check_domain_points_to_vps(subdomain)
            print_dns_check_result(subdomain, match, vps_ip, resolved_ips)

            if not match:
                console.print(
                    f"\n[red]✗ Subdomain '{subdomain}' does not point to this VPS.[/red]\n"
                    "[dim]Add the DNS A record first, or use --skip-dns-check.[/dim]"
                )
                sys.exit(1)

        except DNSError as e:
            console.print(f"\n[red]✗ DNS Error: {e}[/red]")
            sys.exit(1)
    else:
        console.print("\n[bold]Step 1/5:[/bold] DNS check [yellow]SKIPPED[/yellow]")

    # Step 2: Ensure nginx running & check target network
    console.print("\n[bold]Step 2/5:[/bold] Ensuring nginx is running & checking target network...")
    try:
        ensure_nginx_running()
        check_target_network_status(target)
    except DockerError as e:
        console.print(f"\n[red]✗ Docker Error: {e}[/red]")
        sys.exit(1)

    # Step 3: HTTP challenge config
    console.print("\n[bold]Step 3/5:[/bold] Creating HTTP challenge config...")
    backup_path = backup_config(subdomain)

    try:
        http_config = render_http_challenge_config(subdomain, www=False)
        write_config(subdomain, http_config)

        success, msg = reload_nginx()
        if not success:
            console.print(f"[red]✗ Nginx reload failed: {msg}[/red]")
            if backup_path:
                restore_config(subdomain, backup_path)
            else:
                remove_config(subdomain)
            sys.exit(1)
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
        if backup_path:
            restore_config(subdomain, backup_path)
        sys.exit(1)

    # Step 4: Request certificate
    console.print("\n[bold]Step 4/5:[/bold] Requesting SSL certificate...")
    try:
        cert_domain = request_subdomain_certificate(
            subdomain, reuse_parent=reuse_cert, email=email
        )
    except (CertbotError, DockerError) as e:
        console.print(f"\n[red]✗ Certbot Error:[/red]\n{e}")
        console.print("\n[yellow]Rolling back...[/yellow]")
        if backup_path:
            restore_config(subdomain, backup_path)
        else:
            remove_config(subdomain)
        reload_nginx()
        sys.exit(1)

    # Step 5: Write final SSL config
    console.print("\n[bold]Step 5/5:[/bold] Applying final SSL config...")
    try:
        ssl_config = render_ssl_config(
            subdomain, target, www=False, cert_domain=cert_domain
        )
        write_config(subdomain, ssl_config)

        test_ok, test_msg = test_nginx_config()
        if not test_ok:
            console.print(f"[red]✗ Nginx config test failed: {test_msg}[/red]")
            console.print("[yellow]Rolling back...[/yellow]")
            if backup_path:
                restore_config(subdomain, backup_path)
            else:
                write_config(subdomain, http_config)
            reload_nginx()
            sys.exit(1)

        reload_ok, reload_msg = reload_nginx()
        if not reload_ok:
            console.print(f"[red]✗ Nginx reload failed: {reload_msg}[/red]")
            if backup_path:
                restore_config(subdomain, backup_path)
            sys.exit(1)

        cleanup_old_backups(subdomain)

    except Exception as e:
        console.print(f"[red]✗ Error applying SSL config: {e}[/red]")
        if backup_path:
            restore_config(subdomain, backup_path)
        sys.exit(1)

    console.print(Panel(
        f"[green]✓ Subdomain '{subdomain}' successfully configured![/green]\n\n"
        f"  🌐 https://{subdomain}\n"
        f"  🔒 SSL Certificate: {cert_domain}\n"
        f"  🔄 Proxy target: {target}",
        title="✅ Success",
        border_style="green",
    ))


# ── Command: list ───────────────────────────────────────────────────


@cli.command("list")
def list_domains():
    """List all active domains with target and SSL certificate status.

    Example:
        proxy list
    """
    configs = list_active_configs()

    if not configs:
        console.print("\n[yellow]No domains configured yet.[/yellow]")
        console.print("[dim]Use 'proxy add-domain' to add one.[/dim]\n")
        return

    table = Table(title="🌐 Active Domains")
    table.add_column("#", style="dim", width=4)
    table.add_column("Domain", style="cyan bold")
    table.add_column("Server Names", style="white")
    table.add_column("Target", style="green")
    table.add_column("SSL", style="white")
    table.add_column("Certificate Status", style="white")

    for i, cfg in enumerate(configs, 1):
        domain = cfg["domain"]
        names = ", ".join(cfg["server_names"])
        target = cfg["target"]
        ssl_icon = "🔒" if cfg["has_ssl"] else "🔓"
        cert_domain = str(cfg.get("cert_domain") or domain)
        cert_status = get_cert_status(cert_domain)

        table.add_row(
            str(i),
            domain,
            names,
            target,
            ssl_icon,
            cert_status,
        )

    console.print()
    console.print(table)
    console.print()


# ── Command: remove ─────────────────────────────────────────────────


@cli.command("remove")
@click.argument("domain")
@click.option("--remove-cert", is_flag=True, default=False,
              help="Also delete SSL certificate files")
@click.confirmation_option(prompt="Are you sure you want to remove this domain?")
def remove_domain(domain: str, remove_cert: bool):
    """Remove domain configuration.

    Examples:
        proxy remove example.com
        proxy remove example.com --remove-cert
    """
    console.print(f"\n[bold]Removing domain:[/bold] {domain}")

    if not config_exists(domain):
        console.print(f"[red]✗ Configuration for '{domain}' not found.[/red]")
        sys.exit(1)

    # Backup before remove
    backup_config(domain)

    # Remove config
    remove_config(domain)

    # Remove certificate if requested
    if remove_cert:
        console.print("\n[yellow]Removing SSL certificate...[/yellow]")
        remove_certificate(domain)

    # Reload nginx
    console.print("\n[yellow]Reloading nginx...[/yellow]")
    success, msg = reload_nginx()
    if success:
        console.print(f"[green]✓[/green] Nginx reloaded")
    else:
        console.print(f"[yellow]⚠️ Nginx reload: {msg}[/yellow]")

    console.print(Panel(
        f"[green]✓ Domain '{domain}' successfully removed.[/green]",
        title="✅ Removed",
        border_style="green",
    ))


# ── Command: test ───────────────────────────────────────────────────


@cli.command("test")
def test_config():
    """Test Nginx configuration syntax (nginx -t).

    Example:
        proxy test
    """
    console.print("\n[bold]Testing Nginx configuration...[/bold]")
    success, msg = test_nginx_config()

    if success:
        console.print(Panel(
            f"[green]✓ Nginx configuration syntax is OK![/green]\n\n[dim]{msg}[/dim]",
            title="✅ Syntax OK",
            border_style="green",
        ))
    else:
        console.print(Panel(
            f"[red]✗ Nginx configuration test failed![/red]\n\n{msg}",
            title="❌ Test Failed",
            border_style="red",
        ))
        sys.exit(1)


# ── Command: reload ──────────────────────────────────────────────────


@cli.command("reload")
def reload_config():
    """Reload Nginx service (nginx -s reload).

    Example:
        proxy reload
    """
    console.print("\n[bold]Testing configuration before reload...[/bold]")
    test_ok, test_msg = test_nginx_config()
    if not test_ok:
        console.print(f"[red]✗ Cannot reload: Nginx config test failed![/red]\n{test_msg}")
        sys.exit(1)

    console.print("[yellow]Reloading Nginx...[/yellow]")
    reload_ok, reload_msg = reload_nginx()

    if reload_ok:
        console.print(f"[green]✓[/green] {reload_msg}")
    else:
        console.print(f"[red]✗ Reload failed: {reload_msg}[/red]")
        sys.exit(1)


# ── Command: renew ───────────────────────────────────────────────────


@cli.command("renew")
@click.option("--setup-cron", is_flag=True, default=False,
              help="Show crontab setup instructions for auto-renewal")
def renew_cmd(setup_cron: bool):
    """Renew all SSL certificates and reload Nginx.

    Examples:
        proxy renew
        proxy renew --setup-cron
    """
    if setup_cron:
        console.print(Panel(
            "[bold]⏰ Crontab Setup Instructions[/bold]\n\n"
            "To auto-renew certificates daily at 3:00 AM, add this entry to crontab:\n\n"
            "  [cyan]crontab -e[/cyan]\n\n"
            "Add line:\n"
            "  [green]0 3 * * * proxy renew >> /var/log/certbot-renew.log 2>&1[/green]\n\n"
            "Or using script:\n"
            "  [green]0 3 * * * /path/to/nginx-proxy-helper/scripts/renew-certs.sh >> /var/log/certbot-renew.log 2>&1[/green]",
            title="⏰ Auto-Renewal Setup",
            border_style="blue",
        ))
        return

    console.print("\n[bold]Starting SSL certificate renewal...[/bold]")

    ensure_nginx_running()
    success, output = renew_certificates()

    if output:
        console.print(f"\n[dim]{output}[/dim]")

    if success:
        console.print("\n[yellow]Reloading Nginx...[/yellow]")
        reload_ok, reload_msg = reload_nginx()
        if reload_ok:
            console.print("[bold green]✅ Renewal completed & Nginx reloaded![/bold green]")
        else:
            console.print(f"[yellow]⚠️ Certificates renewed, but Nginx reload failed: {reload_msg}[/yellow]")
    else:
        console.print("[red]✗ Renewal completed with errors.[/red]")


# ── Command: dns-check ──────────────────────────────────────────────


@cli.command("dns-check")
@click.argument("domain")
def dns_check_cmd(domain: str):
    """Check if domain A records point to this VPS IP.

    Example:
        proxy dns-check example.com
    """
    console.print(f"\n[bold]Checking DNS for:[/bold] {domain}")

    try:
        match, vps_ip, resolved_ips = check_domain_points_to_vps(domain)
        print_dns_check_result(domain, match, vps_ip, resolved_ips)

        if is_subdomain(domain):
            parent = get_parent_domain(domain)
            if parent:
                console.print(f"\nChecking parent domain: {parent}...")
                try:
                    p_match, _, p_ips = check_domain_points_to_vps(parent)
                    print_dns_check_result(parent, p_match, vps_ip, p_ips)
                except DNSError:
                    pass

        if not match:
            sys.exit(1)

    except DNSError as e:
        console.print(f"\n[red]✗ DNS Check Error: {e}[/red]")

        try:
            from nginx_proxy_helper.lib.dns import get_public_ip, print_dns_instructions
            vps_ip = get_public_ip()
            print_dns_instructions(domain, vps_ip)
        except DNSError:
            console.print(
                "\n[dim]Ensure domain is registered and DNS A records are configured.[/dim]"
            )

        sys.exit(1)


# ── Command: check ──────────────────────────────────────────────────


@cli.command("check")
def check_deps():
    """Check system dependencies, Docker status, network, and Python packages.

    Example:
        proxy check
    """
    from nginx_proxy_helper.lib.checker import run_full_check

    console.print("\n[bold]🔍 nginx-proxy-helper — Dependency Check[/bold]")

    all_ok = run_full_check()

    if not all_ok:
        sys.exit(1)


# ── Command: auto-install ───────────────────────────────────────────


@cli.command("auto-install")
def auto_install_cmd():
    """Auto-install Docker/Compose, setup network, and launch containers.

    Examples:
        proxy auto-install
    """
    from nginx_proxy_helper.lib.installer import setup_vps_environment

    success = setup_vps_environment()
    if not success:
        sys.exit(1)


@cli.command("install", hidden=True)
def install_alias():
    """Alias for auto-install."""
    auto_install_cmd()


# ── Command: uninstall ──────────────────────────────────────────────


@cli.command("uninstall")
def uninstall_cmd():
    """Uninstall nginx-proxy-helper (interactive prompt).

    Examples:
        proxy uninstall
    """
    import os
    import subprocess
    from nginx_proxy_helper.config import PROJECT_ROOT

    script_path = PROJECT_ROOT / "uninstall.sh"
    if script_path.exists():
        subprocess.run(["/bin/bash", str(script_path)])
    else:
        cmd = "/bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/mhiqrambg/nginx-proxy-helper/main/uninstall.sh)\""
        subprocess.run(cmd, shell=True)


# ── Command: export ─────────────────────────────────────────────────


@cli.command("export")
@click.argument("destination", default="/root/nginx-alpine", type=click.Path())
def export_cmd(destination: str):
    """Export standalone Nginx setup (docker-compose, configs, SSL certs) to a folder.

    Allows running Nginx independently outside of ~/.nginx-proxy-helper.

    Examples:
        proxy export
        proxy export /root/nginx-alpine
        proxy export /var/www/my-proxy
    """
    from pathlib import Path

    dest_path = Path(destination).resolve()
    console.print(f"\n[bold]Exporting standalone Nginx setup to:[/bold] [cyan]{dest_path}[/cyan]")

    try:
        exported_path = export_standalone_setup(dest_path)
        console.print(Panel(
            f"[green]✓ Standalone Nginx setup exported successfully![/green]\n\n"
            f"  📁 Folder: [cyan]{exported_path}[/cyan]\n\n"
            f"  [bold]To run independently without proxy CLI:[/bold]\n"
            f"    [white]cd {exported_path}[/white]\n"
            f"    [white]docker compose up -d[/white]",
            title="📦 Export Complete",
            border_style="green",
        ))
    except Exception as e:
        console.print(f"[red]✗ Export failed: {e}[/red]")
        sys.exit(1)


# ── Main ────────────────────────────────────────────────────────────


if __name__ == "__main__":
    cli()

