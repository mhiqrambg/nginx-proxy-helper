# nginx-proxy-helper 🔧

CLI tool untuk mengelola **reverse proxy Nginx + SSL Certbot** di VPS dengan Docker Compose.

Otomatis generate konfigurasi Nginx, request sertifikat SSL via Let's Encrypt, dan manage semua domain dari satu command.

---

## ✨ Fitur

| Command | Deskripsi |
|---------|-----------|
| `proxy add-domain` | Tambah domain baru + auto SSL |
| `proxy add-subdomain` | Tambah subdomain (reuse/separate cert) |
| `proxy list` | List semua domain aktif + status cert |
| `proxy remove` | Hapus domain + opsional hapus cert |
| `proxy test` | Test nginx config (`nginx -t`) |
| `proxy reload` | Reload nginx |
| `proxy renew` | Renew semua sertifikat SSL |
| `proxy dns-check` | Cek apakah DNS sudah mengarah ke VPS |
| `proxy check` | Cek semua dependency (Docker, Python, dll) |

---

## 📋 Prerequisites

- **Python** 3.8+
- **Docker** & **Docker Compose** v2
- **VPS** dengan public IP
- Domain yang sudah pointing ke IP VPS

---

## 🚀 Installation

### Quick Install (Recommended)

**macOS / Linux** — open terminal and run:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/mhiqrambg/nginx-proxy-helper/main/install.sh)"
```

This will:
- Clone the repo to `~/.nginx-proxy-helper`
- Create a Python virtual environment
- Install all dependencies
- Add `proxy` command to your PATH

### Manual Install

```bash
git clone https://github.com/mhiqrambg/nginx-proxy-helper.git
cd nginx-proxy-helper
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Post-Install Setup

```bash
# Create Docker network (required, run once)
docker network create nginx-network

# Start Nginx & Certbot services
cd ~/.nginx-proxy-helper/nginx-alpine  # or your clone path
docker compose up -d

# Verify everything is ready
proxy check
```

### Environment Variables (Optional)

```bash
# Email untuk Let's Encrypt notifications
export CERTBOT_EMAIL="admin@example.com"

# Gunakan staging server untuk testing
export CERTBOT_STAGING=1

# Custom project root (jika tidak di default location)
export NGINX_PROXY_ROOT=/path/to/nginx-proxy-helper
```

### Update

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/mhiqrambg/nginx-proxy-helper/main/update.sh)"
```

### Uninstall

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/mhiqrambg/nginx-proxy-helper/main/uninstall.sh)"
```

---

## 📖 Usage

### Tambah Domain Baru

```bash
# Domain utama dengan SSL + redirect www
proxy add-domain example.com --target app:3000 --www

# Dengan email untuk Let's Encrypt
proxy add-domain example.com --target app:3000 --email admin@example.com

# Skip DNS check (jika yakin DNS sudah benar)
proxy add-domain example.com --target app:3000 --skip-dns-check
```

**Alur otomatis:**
1. ✅ Cek DNS — pastikan domain resolve ke IP VPS
2. ✅ Buat HTTP-only config — untuk ACME challenge
3. ✅ Request SSL certificate — via certbot
4. ✅ Ganti ke SSL config — reverse proxy + HTTPS
5. ✅ Reload nginx — domain aktif!

### Tambah Subdomain

```bash
# Reuse sertifikat parent domain (default)
proxy add-subdomain api.example.com --target api-service:8080

# Request sertifikat terpisah
proxy add-subdomain blog.example.com --target ghost:2368 --separate-cert
```

### List Domain Aktif

```bash
proxy list
```

Output:
```
┌───┬─────────────────┬──────────┬──────┬──────────────────────┐
│ # │ Domain          │ Target   │ SSL  │ Certificate Status   │
├───┼─────────────────┼──────────┼──────┼──────────────────────┤
│ 1 │ example.com     │ app:3000 │ 🔒   │ 🟢 Valid (89 days)   │
│ 2 │ api.example.com │ api:8080 │ 🔒   │ 🟢 Valid (89 days)   │
│ 3 │ blog.example.com│ ghost:23 │ 🔓   │ ❌ No certificate    │
└───┴─────────────────┴──────────┴──────┴──────────────────────┘
```

### Hapus Domain

```bash
# Hapus config saja
proxy remove example.com

# Hapus config + sertifikat
proxy remove example.com --remove-cert
```

### Test & Reload Nginx

```bash
# Test konfigurasi
proxy test

# Reload nginx
proxy reload
```

### Cek DNS

```bash
proxy dns-check example.com
```

Output:
```
┌──────┬─────────────┬──────────────┬──────────┐
│ Type │ Name        │ Value        │ Status   │
├──────┼─────────────┼──────────────┼──────────┤
│ A    │ example.com │ 123.45.67.89 │ ✅ Match │
└──────┴─────────────┴──────────────┴──────────┘
```

### Renew Sertifikat

```bash
# Renew manual
proxy renew

# Lihat instruksi setup crontab
proxy renew --setup-cron
```

---

## ⏰ Auto-Renewal Crontab

### Menggunakan script:

```bash
# Jadikan executable
chmod +x scripts/renew-certs.sh

# Edit crontab
crontab -e

# Tambahkan (renew setiap hari jam 3 pagi):
0 3 * * * /path/to/nginx-proxy-helper/scripts/renew-certs.sh >> /var/log/certbot-renew.log 2>&1
```

### Menggunakan proxy command:

```bash
0 3 * * * cd /path/to/nginx-proxy-helper && proxy renew >> /var/log/certbot-renew.log 2>&1
```

---

## 📁 Struktur Project

```
nginx-proxy-helper/
├── pyproject.toml              # Package config
├── README.md                   # Dokumentasi
│
├── nginx_proxy_helper/         # Source code
│   ├── cli.py                  # CLI entrypoint
│   ├── config.py               # Path & settings
│   ├── lib/
│   │   ├── certbot.py          # Certbot operations
│   │   ├── nginx.py            # Nginx config & operations
│   │   ├── dns.py              # DNS resolution
│   │   └── docker.py           # Docker helpers
│   └── templates/
│       ├── http_challenge.conf.j2
│       └── ssl_proxy.conf.j2
│
├── nginx-alpine/               # Docker compose project
│   ├── docker-compose.yml
│   ├── nginx/conf.d/           # Generated configs
│   └── certbot/{conf,www}/     # Certbot data
│
└── scripts/
    └── renew-certs.sh          # Crontab script
```

---

## 🔧 Kustomisasi Template

Template Nginx ada di `nginx_proxy_helper/templates/`:

- **`http_challenge.conf.j2`** — Config sementara untuk ACME validation
- **`ssl_proxy.conf.j2`** — Config final dengan SSL + reverse proxy

Edit template sesuai kebutuhan. Variabel yang tersedia:
- `{{ domain }}` — Domain name
- `{{ target }}` — Proxy target (container:port)
- `{{ www }}` — Boolean, true jika include www alias
- `{{ cert_domain }}` — Domain untuk path sertifikat

---

## 🐛 Troubleshooting

### DNS belum propagate
```
✗ Domain 'example.com' BELUM mengarah ke VPS ini!
```
→ Tunggu 5-30 menit setelah update DNS record, lalu coba lagi.

### Certbot gagal
→ Config otomatis di-rollback. Tidak ada config setengah jadi.
→ Cek apakah port 80 bisa diakses dari internet.

### Nginx config error
```bash
proxy test  # Lihat detail error
```

### Docker tidak jalan
```bash
docker ps                        # Cek container
docker compose -f nginx-alpine/docker-compose.yml logs  # Cek logs
```

---

## 📄 License

MIT
