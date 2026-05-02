# PGOps

**Portable PostgreSQL + Web App Platform for Windows & macOS**

PGOps is a self-contained desktop application that bundles PostgreSQL, RustFS object storage, pgAdmin 4, Caddy reverse proxy, and FrankenPHP into a single orchestration console. It's built for developers who need a full local server stack — with LAN access, mDNS discovery, TLS via mkcert, and one-click Laravel deployment — without touching system configuration files or running shell scripts.

---

## Table of Contents

- [What PGOps Does](#what-pgops-does)
- [Requirements](#requirements)
- [Installation](#installation)
- [First Launch](#first-launch)
- [Running in Development Mode](#running-in-development-mode)
- [Building for Distribution](#building-for-distribution)
- [Architecture Overview](#architecture-overview)
- [User Interface Guide](#user-interface-guide)
- [CLI Tool](#cli-tool)
- [Configuration Reference](#configuration-reference)
- [Data and File Locations](#data-and-file-locations)
- [Security](#security)
- [Networking and DNS](#networking-and-dns)
- [SSL / TLS with mkcert](#ssl--tls-with-mkcert)
- [Scheduled Backups](#scheduled-backups)
- [Windows Service Mode](#windows-service-mode)
- [Deploying Laravel Apps](#deploying-laravel-apps)
- [RustFS Object Storage](#rustfs-object-storage)
- [Troubleshooting](#troubleshooting)

---

## What PGOps Does

PGOps manages every layer of a local development or small-production stack from a single GUI window:

**Infrastructure services** — PostgreSQL 16, RustFS S3 storage, pgAdmin 4, Caddy reverse proxy, FrankenPHP PHP server. Each starts, stops, and is monitored from the Server tab.

**LAN discovery** — mDNS broadcasts `pgops.local` and every deployed app subdomain so any device on the same WiFi can connect with zero configuration.

**TLS everywhere** — mkcert generates a locally trusted certificate authority. Once installed, all `*.pgops.local` domains are trusted in browsers on the host machine with no warnings. Client devices import the CA once.

**Database management** — create isolated PostgreSQL databases, each with its own owner role. Browse tables and run SQL from a built-in editor. Live activity monitoring shows connections, cache hit ratios, TPS, and uptime.

**Object storage** — per-bucket RustFS access keys with scoped IAM-style policies. Public/private toggles, folder management, backup and restore.

**App deployment** — provision and run Laravel apps in one wizard. Each app gets a database, a bucket, a generated `.env`, and a `*.pgops.local` subdomain served over HTTPS.

**Backup scheduling** — automated pg_dump backups on hourly, daily, or weekly cadences with configurable retention.

---

## Requirements

**Runtime**
- Python 3.10 or later
- PostgreSQL binaries are downloaded on first launch (~150 MB) if not bundled

**Python packages** (installed automatically by the run scripts)

```
PyQt6>=6.6.0
requests>=2.31.0
qrcode>=7.4.2
Pillow>=10.0.0
pyinstaller>=6.3.0
psycopg2-binary>=2.9.0
zeroconf>=0.131.0
cryptography>=42.0.0
bcrypt>=4.0.0
dnslib>=0.9.23
GitPython>=3.1.40
psutil>=5.9.0
```

**Build tools** (optional, for producing distributable packages)
- Windows: Inno Setup 6 for a `Setup.exe` installer
- macOS: Homebrew + `create-dmg` for a `.dmg` disk image

---

## Installation

### Windows

**Pre-built installer** — download `PGOps-Setup-x.x.x-Windows.exe` and run it. No administrator rights required for a per-user install.

**From source:**
```bat
git clone https://github.com/yourname/pgops.git
cd pgops
run_dev.bat
```

### macOS

```bash
git clone https://github.com/yourname/pgops.git
cd pgops
chmod +x run_dev.sh
./run_dev.sh
```

### From the .app bundle

Double-click `PGOps.app`. On first launch macOS may show a Gatekeeper prompt — right-click the app and choose Open to proceed.

---

## First Launch

**Step 1 — Create a master password.** PGOps shows a setup screen on the very first launch. This password protects the interface and is stored as a bcrypt hash on disk. It has nothing to do with your database credentials.

**Step 2 — Set up PostgreSQL binaries.** Click **Setup PostgreSQL** on the Server tab. PGOps downloads and extracts the PostgreSQL 16 binaries to your app data directory. This takes about a minute and only happens once.

**Step 3 — Start the server.** Click **▶ START SERVER**. On first start, PGOps initialises a new cluster with these defaults:

| Field | Default |
|-------|---------|
| Host | your LAN IP or `pgops.local` |
| Port | 5432 |
| Username | `postgres` |
| Password | `postgres` |
| Database | `mydb` |

Change these in **Settings** before the first start if you want different values. Changing credentials after initialisation requires deleting the `pgdata` folder.

**Step 4 — Connect.** Copy the connection URI from the Server tab. Or open `pgops.local:5432` directly from your database client.

---

## Running in Development Mode

**Windows**
```bat
run_dev.bat
```

**macOS / Linux**
```bash
./run_dev.sh
```

Both scripts run `pip install -r requirements.txt` and launch `main.py`. All data writes to the same app data directory regardless of whether you run from source or a packaged build.

---

## Building for Distribution

### Windows

```bat
build_windows.bat
```

Output:
- `dist\PGOps\PGOps.exe` — portable build
- `dist\installer\PGOps-Setup-1.0.0-Windows.exe` — Inno Setup installer (if Inno Setup is installed)

To bundle PostgreSQL binaries so users skip the download step, place the Windows binary ZIP from EnterpriseDB at `assets\pg_windows.zip` before building.

### macOS

```bash
./build_mac.sh
```

Output:
- `dist/PGOps.app` — app bundle
- `dist/installer/PGOps-1.0.0-macOS.dmg` — drag-to-install image (requires `create-dmg`)

To bundle PostgreSQL for macOS, place the binary ZIP at `assets/pg_mac.zip`.

### CLI binary

`pgops.spec` builds a separate `pgops` CLI executable. It is included automatically in both build scripts.

---

## Architecture Overview

```
PGOps Desktop Application
├── PostgreSQL 16          — pg_ctl / initdb / psql via subprocess
├── RustFS                 — child process, S3-compatible single binary
├── pgAdmin 4              — child process via the bundled Python runtime
├── Caddy                  — reverse proxy, Caddyfile regenerated per deploy
├── FrankenPHP             — one process per deployed app
├── MDNSServer             — zeroconf, publishes pgops.local + app subdomains
├── LandingServer          — stdlib HTTP on port 8080, Caddy proxies it
├── APIServer              — stdlib HTTP on 127.0.0.1:7420 for the CLI
└── BackupScheduler        — daemon thread, pg_dump on a cron-like schedule
```

**Source layout**

```
main.py                     Entry point, auth gate, window launch
pgops_cli.py                CLI tool
pgops.spec                  PyInstaller spec for app + CLI
requirements.txt

src/core/                   Business logic (no Qt imports)
  auth.py                   Master password hashing and verification
  config.py                 Settings load / save
  pg_manager.py             PostgreSQL binary setup and cluster lifecycle
  db_manager.py             Database and role operations
  rustfs_manager.py         RustFS binary management and server control
  bucket_manager.py         RustFS bucket / access-key operations via S3 API
  pgadmin_manager.py        pgAdmin 4 process lifecycle
  caddy_manager.py          Caddyfile generation and Caddy process control
  frankenphp_manager.py     FrankenPHP binary setup and per-app processes
  app_manager.py            App registry, provisioning, git pull, deletion
  api_server.py             Internal REST API (127.0.0.1:7420)
  landing_server.py         pgops.local root landing page
  mdns_server.py            mDNS broadcaster (replaces old DNS server)
  dns_server.py             Hosts-file fallback utilities
  mdns.py                   Legacy mDNS broadcaster (PostgreSQL service record)
  network_info.py           Network interface discovery
  hotspot.py                Windows Mobile Hotspot via WinRT / PowerShell
  scheduler.py              Automated backup scheduler
  service_manager.py        Windows Service registration
  ssl_manager.py            mkcert cert management, postgresql.conf SSL config
  mkcert_manager.py         mkcert binary download, CA install, cert generation
  ip_watcher.py             Background thread that watches for LAN IP changes

src/ui/                     Qt6 interface
  main_window.py            Root window, wires everything together
  sidebar.py                Navigation sidebar
  header_bar.py             Top header bar
  login_dialog.py           Login, setup, and password-change dialogs
  tab_server.py             Server controls and service cards
  tab_activity.py           Live activity dashboard
  tab_databases.py          Database list, table browser, SQL runner
  tab_apps.py               Laravel app deployment and management
  tab_backup.py             Backup and restore UI
  tab_schedule.py           Backup scheduler configuration
  tab_ssl.py                SSL / TLS management
  tab_service.py            Windows Service control
  tab_network.py            Network interfaces, mDNS, hotspot
  tab_dns.py                mDNS status and client setup instructions
  tab_settings.py           App settings
  tab_docs.py               In-app documentation (this tab)
  files_tab.py              RustFS bucket management
  activity_monitor.py       Legacy activity widget
  table_browser.py          Legacy table browser widget
  widgets.py                Shared UI components
  theme.py                  Colour tokens and global stylesheet

assets/                     Optional pre-bundled binaries
  pg_windows.zip            PostgreSQL Windows binaries
  pg_mac.zip                PostgreSQL macOS binaries
  rustfs.exe / rustfs       RustFS server binary
  caddy.exe / caddy         Caddy binary
  frankenphp binary         FrankenPHP binary
```

---

## User Interface Guide

Navigation is in the left sidebar. Upper group: main tools. Lower group: infrastructure and advanced settings.

| Tab | What it does |
|-----|--------------|
| **Servers** | Start and stop PostgreSQL, RustFS, pgAdmin, Caddy, FrankenPHP. View connection details and live log output. |
| **Activity** | Live dashboard: active connections, database sizes, cache hit ratio, transactions per second, server uptime. |
| **Databases** | Create and drop isolated databases. Browse tables with pagination. Run arbitrary SQL. Change role passwords. |
| **Apps** | Deploy and manage Laravel applications via the wizard. Start, stop, restart, pull, view logs, run Artisan commands. |
| **Explorer** | Standalone SQL runner and schema browser for any database. |
| **Storage** | RustFS bucket management: create, drop, rotate keys, toggle public/private, manage folders. |
| **Settings** | Change PostgreSQL credentials, port, autostart preference, and app master password. |
| **Backup** | Manual pg_dump backup and pg_restore restore. |
| **Schedule** | Configure automated backup frequency, time, retention, and which databases to include. |
| **SSL / TLS** | Run mkcert full setup, generate or regenerate certificates, enable/disable SSL on PostgreSQL, export the CA for client devices. |
| **Service** | Register or remove PostgreSQL as a Windows background service. |
| **Network** | View and pin network interfaces, control the legacy mDNS broadcaster, manage the Windows Mobile Hotspot. |
| **DNS** | mDNS status, registered subdomains, hosts-file fallback injection, per-platform client setup instructions, QR code. |
| **Log** | Full application log output. |
| **Docs** | This documentation. |

---

## CLI Tool

The `pgops` CLI communicates with a running PGOps instance over the internal API at `127.0.0.1:7420`. PGOps must be open for CLI commands to work.

```bash
# Check service status
pgops status

# List deployed apps
pgops apps

# Deploy from a ZIP archive
pgops deploy --zip ./myapp.zip --name inventory --display "Inventory Manager"

# Deploy from a Git repository
pgops deploy --git https://github.com/org/app.git --name inventory --branch main

# App lifecycle
pgops start inventory
pgops stop inventory
pgops restart inventory
pgops pull inventory        # git pull + migrate + restart
pgops logs inventory --lines 200
pgops delete inventory

# Database management
pgops db:create mydb myuser --password secret
pgops db:list

# Backup
pgops backup mydb
```

---

## Configuration Reference

Settings are stored in `config.json` in the app data directory and are editable through the Settings tab.

| Key | Default | Description |
|-----|---------|-------------|
| `username` | `postgres` | PostgreSQL admin username |
| `password` | `postgres` | PostgreSQL admin password |
| `database` | `mydb` | Default database name |
| `port` | `5432` | PostgreSQL port |
| `autostart` | `false` | Start PostgreSQL when app opens |
| `preferred_ip` | `""` | Pin the host IP (empty = auto-detect) |
| `caddy_http_port` | `80` | Caddy HTTP port (needs admin if 80) |
| `caddy_https_port` | `443` | Caddy HTTPS port (needs admin if 443) |
| `landing_port` | `8080` | Landing page server port |
| `rustfs_api_port` | `9000` | RustFS S3 API port |
| `rustfs_console_port` | `9001` | RustFS web console port |
| `pgadmin_port` | `5050` | pgAdmin internal port |

**Changing credentials after first start** requires stopping the server and deleting the `pgdata` folder to reinitialise the cluster from scratch.

---

## Data and File Locations

PGOps never writes to `Program Files` or the app bundle. All mutable data lives in:

| Platform | Path |
|----------|------|
| Windows | `%LOCALAPPDATA%\PGOps\` |
| macOS | `~/Library/Application Support/PGOps/` |

Directory layout inside that folder:

```
config.json             App settings
auth.json               Master password hash
pgsql/                  PostgreSQL binaries
pgdata/                 PostgreSQL cluster data directory
postgres.log            PostgreSQL server log
backups/                pg_dump backup files (.dump)
backup_schedule.json    Scheduler configuration
mkcert/                 mkcert binary
certs/                  Generated TLS certificate and key
rustfs-bin/             RustFS server binary
rustfs-data/            RustFS object storage data
pgadmin4-data/          pgAdmin 4 database, sessions, logs
caddy/                  Caddy binary, Caddyfile, data directory
frankenphp/             FrankenPHP binary and per-app PHP ini files
apps/                   Deployed app source files
apps.json               App registry
```

**Uninstalling:** On Windows the uninstaller removes the application binaries but leaves the data directory intact so your databases and files survive. Delete `%LOCALAPPDATA%\PGOps` manually to remove everything.

---

## Security

### Master Password

The master password is hashed with bcrypt (12 rounds) if the `bcrypt` package is available, or PBKDF2-HMAC-SHA256 (300,000 iterations) as a fallback. The hash is stored in `auth.json` and never sent anywhere.

After five failed login attempts, the error message prompts the user to use the Forgot Password flow, which explains how to delete `auth.json` to reset. Databases and stored data are unaffected by a password reset.

### Database Credentials

PostgreSQL is configured with `md5` authentication. The admin password is written to disk only temporarily as a `.pwfile` during `initdb`, and deleted immediately after. `pg_hba.conf` accepts connections from any IP by default to support LAN access — tighten this if needed.

### RustFS Access Keys

Each bucket gets a dedicated access key with an IAM-style policy scoped to that bucket only. Other buckets are unreachable with that key. Secret keys are shown once at creation time and are not stored by PGOps after that point.

### Internal API

The REST API used by the CLI binds exclusively to `127.0.0.1:7420` and is not reachable from the LAN.

---

## Networking and DNS

### mDNS — Zero-Configuration LAN Discovery

PGOps broadcasts `pgops.local` and every deployed app subdomain (`<app>.pgops.local`) using mDNS (Zeroconf/Bonjour). Any device on the same WiFi can reach the services with no DNS configuration.

Platform support:
- **Windows 10/11** — built-in mDNS support, no setup needed
- **macOS / iOS** — native Bonjour, no setup needed
- **Android 12+** — works in most browsers
- **Linux** — requires `avahi-daemon` (`sudo apt install avahi-daemon`)
- **Older Windows** — install Apple Bonjour from `support.apple.com/kb/DL999`

### Hosts File Fallback

If mDNS is blocked (corporate firewall, VPN), use the Inject Hosts File button in the DNS tab. This writes `pgops.local` and all app subdomains to the system hosts file on the PGOps machine only. Requires Administrator / sudo.

### Windows Mobile Hotspot

The Network tab can start and stop a Windows Mobile Hotspot using the WinRT API. When the hotspot is active, its fixed IP (`192.168.137.1`) is auto-detected and can be pinned so connection strings stay stable.

### Firewall

On Windows you may need to allow inbound TCP on the PostgreSQL port. The Network tab shows the exact `netsh` command:

```
netsh advfirewall firewall add rule name="PGOps" dir=in action=allow protocol=TCP localport=5432
```

---

## SSL / TLS with mkcert

PGOps uses [mkcert](https://github.com/FiloSottile/mkcert) to generate locally trusted TLS certificates.

**How it works:** mkcert creates a local CA and installs it into the system trust store (Windows, macOS, Chrome, Firefox). Any certificate it issues is trusted automatically by browsers on the host machine — no warnings, no exceptions needed.

**Setup:** Go to **SSL / TLS** and click **Full Setup (Download + Trust CA + Generate Cert)**. This downloads the mkcert binary, installs the CA, and generates a certificate covering:
- `pgops.local` and `*.pgops.local`
- `localhost` and `127.0.0.1`
- All current LAN IPs

**Other devices:** Export the CA certificate from the SSL tab and import it on each client device once. After import, all `*.pgops.local` domains are trusted on that device automatically. The SSL tab shows step-by-step instructions for Windows, macOS, Android, iOS, and Linux.

**PostgreSQL TLS:** After generating the certificate, click **Enable SSL** on the SSL tab, then restart the server. Connect from clients with `sslmode=require`.

**Caddy:** Uses the same mkcert certificate automatically. All HTTPS subdomains are trusted with no additional configuration.

---

## Scheduled Backups

The Schedule tab configures automatic `pg_dump` backups running in a background thread.

| Setting | Options |
|---------|---------|
| Frequency | Hourly, Daily, Weekly |
| Time | HH:MM for daily / weekly |
| Day of week | Monday – Sunday for weekly |
| Keep last N | Number of backups to retain per database |
| Databases | Per-database checkboxes |

Backups are saved to the `backups/` folder in PostgreSQL custom format (`.dump`). They can be restored through the Backup tab or directly with `pg_restore`.

---

## Windows Service Mode

The Service tab registers PostgreSQL as a Windows background service using `pg_ctl register`. In service mode, PostgreSQL starts at system boot before any user logs in.

Requirements: PGOps must be run as Administrator to install or remove the service. The service is named `PGOps-PostgreSQL` and configured for automatic startup.

---

## Deploying Laravel Apps

Apps are deployed through the Apps tab wizard.

**What the wizard does:**
1. Extracts the ZIP or clones the Git repository
2. Creates an isolated PostgreSQL database and owner role
3. Creates a RustFS bucket with a dedicated access key
4. Writes a `.env` file with all connection details pre-filled
5. Runs `php artisan key:generate`
6. Runs `php artisan migrate --force`
7. Starts a FrankenPHP process serving the app on an internal port
8. Reloads Caddy to route `<slug>.pgops.local` to the app

**Stack types:** The wizard supports Laravel (full provisioning), Static HTML (files only), and Other (files only, no PHP runtime).

**PHP extension management:** Each app has its own `php.ini` generated at deploy time. Use the PHP button on the app row to manage which extensions are activated. Extensions compiled into FrankenPHP are always active; additional extensions can be loaded from `.so` / `.dll` files placed in the FrankenPHP extensions directory.

**Artisan runner:** Click the Artisan button on any app row to open the Artisan console. Commands are grouped by category (Keys, Migrations, Seeding, Caches, Queue, Storage) with live streaming output. There is also a free-text custom command input.

**Git pull:** If an app was deployed from a Git URL, the Pull button runs `git pull`, `artisan migrate`, and `artisan config:cache`, then restarts the app.

**Deletion:** Deleting an app drops its database, drops its RustFS bucket, removes all source files, and removes the PHP ini configuration.

**Laravel .env reference:**
```env
DB_CONNECTION=pgsql
DB_HOST=pgops.local
DB_PORT=5432
DB_DATABASE=myapp_db
DB_USERNAME=myapp_user
DB_PASSWORD=<generated>

FILESYSTEM_DISK=s3
AWS_ACCESS_KEY_ID=<generated>
AWS_SECRET_ACCESS_KEY=<generated>
AWS_DEFAULT_REGION=us-east-1
AWS_BUCKET=myapp-files
AWS_ENDPOINT=https://s3.pgops.local
AWS_USE_PATH_STYLE_ENDPOINT=true
```

---

## RustFS Object Storage

**Setup:** Click **Setup RustFS** on the Storage tab to download the RustFS binary. Then click **▶ Start Storage**.

RustFS is a high-performance, S3-compatible object storage server written in Rust — a drop-in replacement for MinIO with 2.3× faster throughput for small objects and an Apache 2.0 license.

**Access URLs (via Caddy + mkcert):**
- S3 API endpoint: `https://s3.pgops.local`
- Web console: `https://console.pgops.local`

Use the HTTPS Caddy URLs in `.env` files and connection strings. The raw internal HTTP URL (`http://127.0.0.1:9000`) is used only for health checks internally.

**Bucket policies:** Each bucket can be Private (authenticated access only) or Public (anyone can download files via URL). Toggle the policy from the Storage tab.

**Folder management:** Click the 📁 Folders button to create or delete key-prefix folders within a bucket. Deleting a folder removes all objects inside it.

**Credential rotation:** Use Rotate Keys to invalidate the old access key and generate a new one. Update your Laravel `.env` after rotating.

---

## Troubleshooting

**PostgreSQL fails to start**

Check the Log tab. Common causes:
- Port 5432 already in use. Change the port in Settings.
- Corrupt `pgdata` folder. Stop the server, delete `pgdata/` in the app data directory, and restart (this reinitialises the cluster and erases all data).
- Insufficient disk space.

**pgAdmin shows a blank page or fails to load**

Click **Reset & Restart** on the Server tab. This deletes the pgAdmin SQLite database and restarts fresh. Default login: `admin@pgops.com` / `pgopsadmin`.

**pgops.local does not resolve on this machine**

Run mDNS resolution test from the DNS tab. If it fails, try the Inject Hosts File button as a fallback. On Windows, check that the Windows Firewall allows UDP on port 5353.

**pgops.local does not resolve on another device**

Ensure both devices are on the same WiFi. mDNS may be blocked on some corporate or guest networks — in those cases, point the device's DNS server to the PGOps host IP using the instructions in the DNS tab.

**Caddy or HTTPS not working**

Check that the mkcert certificate exists (green status on the SSL tab). If Caddy is using its internal CA instead of mkcert, run Full Setup on the SSL tab and restart Caddy.

**RustFS console shows a connection error in the browser**

Use the direct Caddy HTTPS URL (`https://console.pgops.local`) rather than the raw port. Some browsers enforce HTTPS on `.local` domains via HSTS and refuse plain HTTP connections.

**App deployment fails at artisan migrate**

Check the Log tab for the artisan output. Common causes: the database was not created successfully, missing PHP extensions, or a missing `.env` value. Use the Artisan button to rerun `migrate --force` manually after fixing the issue.

**Forgot master password**

Delete `auth.json` from the app data directory and relaunch. You will be prompted to set a new password. All databases and files are preserved.

**Windows: cmd window flashes briefly**

This is suppressed via `CREATE_NO_WINDOW` on all subprocesses. If you see it on a particular action, report the specific operation.