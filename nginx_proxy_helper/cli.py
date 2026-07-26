"""CLI entrypoint — semua command proxy didefinisikan di sini."""

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
    """🔧 nginx-proxy-helper — Kelola reverse proxy Nginx + SSL Certbot di VPS."""
    ensure_directories()


# ── Command: add-domain ────────────────────────────────────────────


@cli.command("add-domain")
@click.argument("domain")
@click.option("--target", required=True, help="Target proxy (e.g., app:3000)")
@click.option("--www", is_flag=True, default=False, help="Tambahkan www.domain sebagai alias")
@click.option("--email", default=None, help="Email untuk Let's Encrypt")
@click.option("--skip-dns-check", is_flag=True, default=False, help="Skip DNS validation")
@click.option("--force", is_flag=True, default=False, help="Overwrite config yang sudah ada")
def add_domain(domain: str, target: str, www: bool, email: str, skip_dns_check: bool, force: bool):
    """Tambahkan domain baru dengan reverse proxy + SSL.

    Contoh:
        proxy add-domain example.com --target app:3000 --www
        proxy add-domain example.com --target localhost:8080
    """
    console.print(Panel(
        f"[bold]Adding domain:[/bold] {domain}\n"
        f"[bold]Target:[/bold] {target}\n"
        f"[bold]WWW alias:[/bold] {'Yes' if www else 'No'}",
        title="🌐 Add Domain",
        border_style="blue",
    ))

    # Cek apakah config sudah ada
    if config_exists(domain) and not force:
        console.print(
            f"\n[red]✗ Config untuk '{domain}' sudah ada![/red]\n"
            f"[dim]Gunakan --force untuk overwrite.[/dim]"
        )
        sys.exit(1)

    # Step 1: DNS Check
    if not skip_dns_check:
        console.print("\n[bold]Step 1/5:[/bold] Checking DNS records...")
        try:
            match, vps_ip, resolved_ips = check_domain_points_to_vps(domain)
            print_dns_check_result(domain, match, vps_ip, resolved_ips)

            if not match:
                console.print("\n[red]Abort: DNS belum mengarah ke VPS ini.[/red]")
                console.print("[dim]Setelah update DNS, jalankan ulang command ini.[/dim]")
                sys.exit(1)

            # Cek www juga jika diminta
            if www:
                www_domain = f"www.{domain}"
                console.print(f"\n[dim]Checking www alias: {www_domain}...[/dim]")
                try:
                    w_match, _, w_ips = check_domain_points_to_vps(www_domain)
                    if not w_match:
                        console.print(
                            f"[yellow]⚠ www.{domain} belum mengarah ke VPS.[/yellow]\n"
                            f"[dim]Tambahkan CNAME record: www → {domain}[/dim]\n"
                            f"[dim]Atau A record: www → {vps_ip}[/dim]\n"
                        )
                        if not click.confirm("Lanjutkan tanpa www?"):
                            sys.exit(1)
                        www = False
                except DNSError:
                    console.print(f"[yellow]⚠ www.{domain} tidak bisa di-resolve.[/yellow]")
                    if not click.confirm("Lanjutkan tanpa www?"):
                        sys.exit(1)
                    www = False

        except DNSError as e:
            console.print(f"\n[red]✗ DNS Error: {e}[/red]")
            sys.exit(1)
    else:
        console.print("\n[bold]Step 1/5:[/bold] DNS check [yellow]SKIPPED[/yellow]")

    # Step 2: Ensure nginx is running
    console.print("\n[bold]Step 2/5:[/bold] Ensuring nginx is running...")
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
            console.print(f"[red]✗ Nginx reload gagal: {msg}[/red]")
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

        # Test config before reload
        success, msg = test_nginx_config()
        if not success:
            console.print(f"[red]✗ Nginx config test gagal: {msg}[/red]")
            console.print("[yellow]Rolling back to HTTP config...[/yellow]")
            http_config = render_http_challenge_config(domain, www)
            write_config(domain, http_config)
            reload_nginx()
            sys.exit(1)

        # Reload with final config
        success, msg = reload_nginx()
        if not success:
            console.print(f"[red]✗ Nginx reload gagal: {msg}[/red]")
            sys.exit(1)

        cleanup_old_backups(domain)

    except Exception as e:
        console.print(f"[red]✗ Error applying SSL config: {e}[/red]")
        # Rollback to HTTP config (cert sudah ada, bisa dicoba manual)
        http_config = render_http_challenge_config(domain, www)
        write_config(domain, http_config)
        reload_nginx()
        sys.exit(1)

    # Done!
    console.print(Panel(
        f"[bold green]✓ Domain '{domain}' berhasil dikonfigurasi![/bold green]\n\n"
        f"  🌐 http://{domain} → https://{domain}\n"
        f"  🔒 SSL certificate aktif\n"
        f"  🔄 Proxy target: {target}",
        title="✅ Success",
        border_style="green",
    ))


# ── Command: add-subdomain ─────────────────────────────────────────


@cli.command("add-subdomain")
@click.argument("subdomain")
@click.option("--target", required=True, help="Target proxy (e.g., api:3000)")
@click.option("--email", default=None, help="Email untuk Let's Encrypt")
@click.option("--reuse-cert/--separate-cert", default=True,
              help="Reuse sertifikat parent domain atau request terpisah")
@click.option("--skip-dns-check", is_flag=True, default=False, help="Skip DNS validation")
@click.option("--force", is_flag=True, default=False, help="Overwrite config yang sudah ada")
def add_subdomain(subdomain: str, target: str, email: str, reuse_cert: bool,
                  skip_dns_check: bool, force: bool):
    """Tambahkan subdomain dengan reverse proxy + SSL.

    Otomatis reuse sertifikat domain utama jika tersedia.

    Contoh:
        proxy add-subdomain api.example.com --target api-service:8080
        proxy add-subdomain blog.example.com --target ghost:2368 --separate-cert
    """
    if not is_subdomain(subdomain):
        console.print(
            f"[red]✗ '{subdomain}' bukan subdomain. "
            f"Gunakan 'proxy add-domain' untuk domain utama.[/red]"
        )
        sys.exit(1)

    parent = get_parent_domain(subdomain)
    console.print(Panel(
        f"[bold]Adding subdomain:[/bold] {subdomain}\n"
        f"[bold]Parent domain:[/bold] {parent}\n"
        f"[bold]Target:[/bold] {target}\n"
        f"[bold]Certificate:[/bold] {'Reuse parent' if reuse_cert else 'Separate'}",
        title="🌐 Add Subdomain",
        border_style="blue",
    ))

    # Cek config existing
    if config_exists(subdomain) and not force:
        console.print(
            f"\n[red]✗ Config untuk '{subdomain}' sudah ada![/red]\n"
            f"[dim]Gunakan --force untuk overwrite.[/dim]"
        )
        sys.exit(1)

    # Step 1: DNS Check
    if not skip_dns_check:
        console.print("\n[bold]Step 1/5:[/bold] Checking DNS records...")
        try:
            match, vps_ip, resolved_ips = check_domain_points_to_vps(subdomain)
            print_dns_check_result(subdomain, match, vps_ip, resolved_ips)
            if not match:
                console.print("\n[red]Abort: DNS belum mengarah ke VPS ini.[/red]")
                sys.exit(1)
        except DNSError as e:
            console.print(f"\n[red]✗ DNS Error: {e}[/red]")
            sys.exit(1)
    else:
        console.print("\n[bold]Step 1/5:[/bold] DNS check [yellow]SKIPPED[/yellow]")

    # Step 2: Ensure nginx running
    console.print("\n[bold]Step 2/5:[/bold] Ensuring nginx is running...")
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
            console.print(f"[red]✗ Nginx reload gagal: {msg}[/red]")
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

    # Step 5: Final SSL config
    console.print("\n[bold]Step 5/5:[/bold] Applying final SSL config...")
    try:
        ssl_config = render_ssl_config(subdomain, target, www=False, cert_domain=cert_domain)
        write_config(subdomain, ssl_config)

        success, msg = test_nginx_config()
        if not success:
            console.print(f"[red]✗ Nginx config test gagal: {msg}[/red]")
            http_config = render_http_challenge_config(subdomain, www=False)
            write_config(subdomain, http_config)
            reload_nginx()
            sys.exit(1)

        success, msg = reload_nginx()
        if not success:
            console.print(f"[red]✗ Nginx reload gagal: {msg}[/red]")
            sys.exit(1)

        cleanup_old_backups(subdomain)

    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
        http_config = render_http_challenge_config(subdomain, www=False)
        write_config(subdomain, http_config)
        reload_nginx()
        sys.exit(1)

    console.print(Panel(
        f"[bold green]✓ Subdomain '{subdomain}' berhasil dikonfigurasi![/bold green]\n\n"
        f"  🌐 https://{subdomain}\n"
        f"  🔒 Certificate: {cert_domain}\n"
        f"  🔄 Proxy target: {target}",
        title="✅ Success",
        border_style="green",
    ))


# ── Command: list ───────────────────────────────────────────────────


@cli.command("list")
def list_domains():
    """Tampilkan semua domain aktif beserta status sertifikat."""
    configs = list_active_configs()

    if not configs:
        console.print("\n[dim]Belum ada domain yang dikonfigurasi.[/dim]")
        console.print("[dim]Gunakan 'proxy add-domain' untuk menambahkan.[/dim]")
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
        cert_status = get_cert_status(domain)

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
              help="Hapus juga sertifikat SSL")
@click.confirmation_option(prompt="Yakin ingin menghapus domain ini?")
def remove_domain(domain: str, remove_cert: bool):
    """Hapus konfigurasi domain.

    Contoh:
        proxy remove example.com
        proxy remove example.com --remove-cert
    """
    console.print(f"\n[bold]Removing domain:[/bold] {domain}")

    if not config_exists(domain):
        console.print(f"[red]✗ Config untuk '{domain}' tidak ditemukan.[/red]")
        sys.exit(1)

    # Backup sebelum hapus
    backup_config(domain)

    # Hapus config
    remove_config(domain)

    # Hapus sertifikat jika diminta
    if remove_cert:
        console.print("\n[yellow]Removing SSL certificate...[/yellow]")
        remove_certificate(domain)

    # Reload nginx
    console.print("\n[yellow]Reloading nginx...[/yellow]")
    success, msg = reload_nginx()
    if success:
        console.print(f"[green]✓[/green] Nginx reloaded")
    else:
        console.print(f"[yellow]⚠ Nginx reload: {msg}[/yellow]")

    console.print(Panel(
        f"[green]✓ Domain '{domain}' berhasil dihapus.[/green]",
        title="✅ Removed",
        border_style="green",
    ))


# ── Command: test ───────────────────────────────────────────────────


@cli.command("test")
def test_config():
    """Test konfigurasi nginx (nginx -t)."""
    console.print("\n[bold]Testing nginx configuration...[/bold]\n")

    try:
        success, output = test_nginx_config()
    except DockerError as e:
        console.print(f"[red]✗ Docker Error: {e}[/red]")
        console.print("[dim]Pastikan nginx container sedang berjalan.[/dim]")
        sys.exit(1)

    if success:
        console.print(f"[green]✓ Configuration test passed[/green]")
        if output:
            console.print(f"[dim]{output}[/dim]")
    else:
        console.print(f"[red]✗ Configuration test FAILED[/red]")
        console.print(f"\n{output}")
        sys.exit(1)


# ── Command: reload ─────────────────────────────────────────────────


@cli.command("reload")
def reload_cmd():
    """Reload nginx setelah perubahan konfigurasi."""
    console.print("\n[bold]Reloading nginx...[/bold]\n")

    # Test dulu sebelum reload
    success, msg = test_nginx_config()
    if not success:
        console.print(f"[red]✗ Config test failed — reload dibatalkan[/red]")
        console.print(f"\n{msg}")
        sys.exit(1)

    success, msg = reload_nginx()
    if success:
        console.print(f"[green]✓ {msg}[/green]")
    else:
        console.print(f"[red]✗ Reload failed: {msg}[/red]")
        sys.exit(1)


# ── Command: renew ──────────────────────────────────────────────────


@cli.command("renew")
@click.option("--setup-cron", is_flag=True, default=False,
              help="Tampilkan instruksi setup crontab")
def renew_cmd(setup_cron: bool):
    """Renew semua sertifikat SSL dan reload nginx.

    Contoh:
        proxy renew
        proxy renew --setup-cron
    """
    if setup_cron:
        _print_cron_instructions()
        return

    console.print("\n[bold]Renewing SSL certificates...[/bold]\n")

    success, output = renew_certificates()
    if output:
        console.print(f"[dim]{output}[/dim]")

    if success:
        console.print("\n[yellow]Reloading nginx...[/yellow]")
        r_success, r_msg = reload_nginx()
        if r_success:
            console.print(f"[green]✓ Nginx reloaded after renewal[/green]")
        else:
            console.print(f"[yellow]⚠ Nginx reload issue: {r_msg}[/yellow]")
    else:
        console.print("\n[red]✗ Certificate renewal encountered issues.[/red]")
        console.print("[dim]Cek output di atas untuk detail.[/dim]")
        sys.exit(1)


def _print_cron_instructions():
    """Tampilkan instruksi setup crontab untuk auto-renew."""
    console.print(Panel(
        "[bold]Auto-Renewal Crontab Setup[/bold]\n\n"
        "1. Pastikan script renew-certs.sh sudah executable:\n"
        "   [cyan]chmod +x scripts/renew-certs.sh[/cyan]\n\n"
        "2. Edit crontab:\n"
        "   [cyan]crontab -e[/cyan]\n\n"
        "3. Tambahkan baris berikut (renew setiap hari jam 3 pagi):\n"
        "   [cyan]0 3 * * * /path/to/nginx-proxy-helper/scripts/renew-certs.sh "
        ">> /var/log/certbot-renew.log 2>&1[/cyan]\n\n"
        "   Atau gunakan proxy command langsung:\n"
        "   [cyan]0 3 * * * cd /path/to/nginx-proxy-helper && "
        "proxy renew >> /var/log/certbot-renew.log 2>&1[/cyan]\n\n"
        "4. Verifikasi crontab:\n"
        "   [cyan]crontab -l[/cyan]",
        title="⏰ Crontab Setup",
        border_style="yellow",
    ))


# ── Command: dns-check ──────────────────────────────────────────────


@cli.command("dns-check")
@click.argument("domain")
def dns_check(domain: str):
    """Cek apakah A record domain mengarah ke VPS yang benar.

    Contoh:
        proxy dns-check example.com
        proxy dns-check api.example.com
    """
    console.print(f"\n[bold]Checking DNS for:[/bold] {domain}\n")

    try:
        match, vps_ip, resolved_ips = check_domain_points_to_vps(domain)
        print_dns_check_result(domain, match, vps_ip, resolved_ips)
    except DNSError as e:
        console.print(f"[red]✗ {e}[/red]")

        # Coba dapatkan VPS IP untuk instruksi
        try:
            from nginx_proxy_helper.lib.dns import get_public_ip, print_dns_instructions
            vps_ip = get_public_ip()
            print_dns_instructions(domain, vps_ip)
        except DNSError:
            console.print(
                "\n[dim]Pastikan domain sudah didaftarkan dan "
                "DNS record sudah dikonfigurasi.[/dim]"
            )

        sys.exit(1)


# ── Command: check ──────────────────────────────────────────────────


@cli.command("check")
def check_deps():
    """Cek apakah semua dependency yang dibutuhkan sudah terinstall.

    Mengecek: Docker, Docker Compose, Python, OpenSSL,
    Docker network, container status, dan Python packages.

    Contoh:
        proxy check
    """
    from nginx_proxy_helper.lib.checker import run_full_check

    console.print("\n[bold]🔍 nginx-proxy-helper — Dependency Check[/bold]")

    all_ok = run_full_check()

    if not all_ok:
        sys.exit(1)


# ── Command: install ────────────────────────────────────────────────


@cli.command("install")
def install_cmd():
    """Install Docker & Docker Compose (jika belum ada), buat docker network, dan jalankan container.

    Menyiapkan seluruh environment VPS secara otomatis.

    Contoh:
        proxy install
    """
    from nginx_proxy_helper.lib.installer import setup_vps_environment

    success = setup_vps_environment()
    if not success:
        sys.exit(1)


# ── Main ────────────────────────────────────────────────────────────


if __name__ == "__main__":
    cli()
