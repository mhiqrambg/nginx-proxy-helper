# nginx-proxy-helper 🔧

CLI tool to manage **Nginx Reverse Proxy + Let's Encrypt SSL Certbot** on your VPS using Docker Compose.

Automatically generates Nginx configurations, requests SSL certificates via Let's Encrypt, validates DNS records, auto-connects container networks, consolidates subdomain certificates, exports standalone deployments, and handles automatic rollbacks on errors — all from a single command line interface.

---

## ✨ Features

| Command | Description |
|---------|-------------|
| `proxy add-domain` | Add a new main domain with automated SSL & optional `www` alias |
| `proxy add-subdomain` | Add a subdomain (supports certificate reuse or separate certs) |
| `proxy list` | List all active domains, proxy targets, and SSL certificate status |
| `proxy remove` | Remove domain configuration (with interactive SSL certificate cleanup) |
| `proxy test` | Test Nginx configuration (`docker exec nginx nginx -t`) |
| `proxy reload` | Reload Nginx service (`docker exec nginx nginx -s reload`) |
| `proxy renew` | Renew all SSL certificates (or consolidate subdomains with `--sync`) |
| `proxy dns-check` | Check if domain A records point to your VPS IP |
| `proxy check` | Validate system dependencies (Docker, Python, network, containers) |
| `proxy auto-install` | Auto-install Docker/Compose, setup network, and launch containers |
| `proxy export` | Export standalone Nginx setup & certs to any folder (e.g. `/root/nginx-alpine`) |
| `proxy uninstall` | Interactive uninstaller (export to standalone or complete removal) |

---

## 📋 Prerequisites

- **Python** 3.8+
- **Docker** & **Docker Compose** v2 (or let `proxy auto-install` install them automatically)
- **VPS** with a public IP address
- A domain name with DNS A records pointing to your VPS IP

---

## 🚀 Recommended Step-by-Step Setup Guide

Follow these recommended stages for a seamless setup on a fresh VPS:

```mermaid
flowchart TD
    A["1. Install CLI"] --> B["2. Setup VPS Environment\n(proxy auto-install)"]
    B --> C["3. Add DNS A Record at Registrar"]
    C --> D["4. Verify DNS\n(proxy dns-check)"]
    D --> E["5. Add Domain + Auto SSL\n(proxy add-domain)"]
```

### Stage 1: Install `nginx-proxy-helper`

Run the one-line installer on your VPS or local terminal:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/mhiqrambg/nginx-proxy-helper/main/install.sh)"
```

*This automatically clones the repo to `~/.nginx-proxy-helper`, sets up a virtual environment, installs dependencies, and configures the `proxy` command in your PATH.*

### Stage 2: Initialize VPS Environment

Run `proxy auto-install` to prepare the environment automatically:

```bash
proxy auto-install
```

This single command will:
- Install Docker & Docker Compose if missing (Linux)
- Ensure Docker daemon is running
- Create the external Docker network `nginx-network`
- Start Nginx and Certbot containers in `~/.nginx-proxy-helper/nginx-alpine`

### Stage 3: Add DNS A Record in Domain Registrar

In your domain registrar dashboard (Cloudflare, Namecheap, GoDaddy, etc.), add an **A Record**:

| Type | Name / Host | Value / Target | TTL |
|:---|:---|:---|:---|
| **A** | `@` (or subdomain like `api`) | `YOUR_VPS_IP` | Auto / 3600 |
| **A** | `www` (optional) | `YOUR_VPS_IP` | Auto / 3600 |

*(If using Cloudflare, set proxy mode to **DNS Only / Gray Cloud** during initial SSL verification).*

### Stage 4: Verify DNS Propagation

Check if your domain points correctly to your VPS:

```bash
proxy dns-check example.com
```

Ensure the status shows `✅ Match`.

### Stage 5: Add Domain & Automatic SSL

Run `proxy add-domain` to generate Nginx configs and obtain SSL certificates automatically:

```bash
# Target container on nginx-network
proxy add-domain example.com --target myapp:3000 --www

# Or target host service
proxy add-domain example.com --target host.docker.internal:8080 --www
```

---

## 📖 Installation & Updates

### Quick Install (Recommended)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/mhiqrambg/nginx-proxy-helper/main/install.sh)"
```

### Manual Install

```bash
git clone https://github.com/mhiqrambg/nginx-proxy-helper.git
cd nginx-proxy-helper
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Update CLI

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/mhiqrambg/nginx-proxy-helper/main/update.sh)"
```

### Interactive Uninstall

```bash
proxy uninstall
# or
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/mhiqrambg/nginx-proxy-helper/main/uninstall.sh)"
```

---

## 💻 Detailed Usage

### Add Main Domain

```bash
# Main domain with SSL & www redirect
proxy add-domain example.com --target app:3000 --www

# With email address for Let's Encrypt notifications
proxy add-domain example.com --target app:3000 --email admin@example.com

# Force overwrite existing configuration
proxy add-domain example.com --target app:3000 --force
```

### Add Subdomain

```bash
# Automatic cert handling (uses separate or parent cert based on availability)
proxy add-subdomain api.example.com --target api-service:8080

# Explicitly request separate SSL certificate
proxy add-subdomain blog.example.com --target ghost:2368 --separate-cert
```

### Consolidate / Sync Subdomain Certificates

Consolidate all active subdomains under a domain into a single unified master SSL certificate:

```bash
proxy renew --sync example.com
```

### Export Standalone Setup

Export Nginx configs, SSL certs, and Docker Compose files to any folder to run independently outside of CLI:

```bash
proxy export /root/nginx-alpine
cd /root/nginx-alpine && docker compose up -d
```

### List Active Domains

```bash
proxy list
```

Example Output:
```
┌───┬─────────────────┬─────────────────┬──────────────┬─────┬────────────────────┐
│ # │ Domain          │ Server Names    │ Target       │ SSL │ Certificate Status │
├───┼─────────────────┼─────────────────┼──────────────┼─────┼────────────────────┤
│ 1 │ example.com     │ example.com     │ app:3000     │ 🔒  │ 🟢 Valid (89 days) │
│ 2 │ api.example.com │ api.example.com │ api:8080     │ 🔒  │ 🟢 Valid (89 days) │
└───┴─────────────────┴─────────────────┴──────────────┴─────┴────────────────────┘
```

### Remove Domain

```bash
# Remove domain (prompts interactively for SSL cert deletion)
proxy remove example.com

# Force delete config + SSL certificate
proxy remove example.com --remove-cert
```

### Test & Reload Nginx

```bash
# Test Nginx configuration syntax (docker exec nginx nginx -t)
proxy test

# Reload Nginx service (docker exec nginx nginx -s reload)
proxy reload
```

---

## ⏰ Auto-Renewal Setup

### In-Container Automatic Renewal (Default — Zero Config Needed)

The running `certbot` Docker container automatically checks and renews certificates **every 12 hours**, and `nginx` container automatically reloads **every 6 hours**.

### OS Crontab Setup (Optional Backup)

To setup additional daily OS renewal check:

```bash
proxy renew --setup-cron
```

Or add to crontab manually (`crontab -e`):
```cron
0 3 * * * proxy renew >> /var/log/certbot-renew.log 2>&1
```

---

## 📁 Project Structure

```
nginx-proxy-helper/
├── pyproject.toml              # Package config & dependencies
├── README.md                   # Documentation
├── install.sh                  # One-line installer
├── update.sh                   # One-line updater
├── uninstall.sh                # Interactive uninstaller
│
├── nginx_proxy_helper/         # Source code
│   ├── cli.py                  # CLI entrypoint (Click subcommands)
│   ├── config.py               # Paths, discovery & settings
│   ├── lib/
│   │   ├── certbot.py          # Certbot SSL manager & sync/consolidation
│   │   ├── nginx.py            # Nginx config generator & export helper
│   │   ├── dns.py              # DNS resolution & conflict detection
│   │   ├── docker.py           # Docker exec & network auto-connect
│   │   ├── checker.py          # Dependency status scanner
│   │   └── installer.py        # Automated VPS Docker environment setup
│   └── templates/
│       ├── http_challenge.conf.j2  # Temporary ACME challenge template
│       └── ssl_proxy.conf.j2       # Production SSL reverse proxy template
│
├── nginx-alpine/               # Docker Compose setup
│   ├── docker-compose.yml
│   ├── nginx/conf.d/           # Generated Nginx config files
│   │   └── 00-default.conf     # Catch-all HTTP/HTTPS 404 fallback server
│   ├── nginx/ssl/              # Fallback dummy self-signed SSL certs
│   └── certbot/{conf,www}      # Shared Certbot webroot & live certs
│
└── scripts/
    └── renew-certs.sh          # Crontab auto-renewal script
```

---

## 🐛 Troubleshooting

### Multiple Conflicting A Records
```
⚠️ CRITICAL DNS WARNING: Multiple conflicting A records detected!
```
→ Delete extra IP records from your DNS dashboard so Let's Encrypt doesn't hit a mismatch IP.

### Target Container Not Found
```
⚠ Target container 'myapp' is not connected to 'nginx-network'.
```
→ Run `docker network connect nginx-network myapp` or let `proxy add-domain` auto-connect it.

---

## 📄 License

MIT
