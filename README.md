# PGOps

**Portable PostgreSQL + Web App Platform for Windows & macOS**

PGOps is a desktop application that bundles PostgreSQL, MinIO object storage, pgAdmin 4, Caddy reverse proxy, and FrankenPHP into a single self-contained tool. It's designed for developers who need to run a full local server stack — with LAN access, DNS resolution, SSL, and one-click Laravel app deployment — without touching system configuration.

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [First Launch](#first-launch)
- [Running in Development Mode](#running-in-development-mode)
- [Building for Distribution](#building-for-distribution)
- [Architecture Overview](#architecture-overview)
- [User Interface](#user-interface)
- [CLI Tool](#cli-tool)
- [Configuration](#configuration)
- [Data & File Locations](#data--file-locations)
- [Security](#security)
- [Network & DNS](#network--dns)
- [SSL / TLS](#ssl--tls)
- [Scheduled Backups](#scheduled-backups)
- [Windows Service Mode](#windows-service-mode)
- [Deploying Laravel Apps](#deploying-laravel-apps)
- [MinIO Storage](#minio-storage)
- [Troubleshooting](#troubleshooting)

---

## Features

**Core Infrastructure**
- Embedded PostgreSQL 16.2 — downloads and installs binaries on first run
- MinIO S3-compatible object storage with per-bucket access keys
- pgAdmin 4 web UI with auto-configured credentials
- Caddy reverse proxy routing `*.pgops.local` to deployed apps
- FrankenPHP server for running Laravel applications

**Networking**
- mDNS broadcasting (`pgops.local`) — works on LAN and mobile hotspot without DNS server config
- Built-in DNS server resolving `*.pgops.local` — point other devices at the host IP once and all subdomains work
- Windows Mobile Hotspot control via WinRT (start/stop from within the app)
- Network interface detection with hotspot, LAN, and Wi-Fi classification
- IP pinning — lock to a specific interface so connection strings stay stable

**Database Management**
- Create and drop isolated databases, each with its own owner role and credentials
- Change role passwords
- Table browser and inline SQL runner with pagination
- Live activity monitor: active connections, database sizes, cache hit ratio, uptime, transactions per second
- Connection termination

**Backup & Restore**
- pg_dump / pg_restore in custom format
- Automated scheduler (hourly, daily, or weekly) with configurable retention
- Per-database selection for scheduled backups

**Security**
- Master password protection on app launch (bcrypt or PBKDF2, never plaintext)
- Self-signed TLS certificate generation using the `cryptography` library (no OpenSSL binary required)
- SSL enable/disable for PostgreSQL with certificate export for clients
- Scoped MinIO policies — each bucket's access key can only reach that bucket

**Developer Tools**
- `pgops` CLI for scripted deployments, database management, and log streaming
- Internal REST API on `127.0.0.1:7420` (LAN-isolated)
- Landing page server at `pgops.local` listing deployed apps and DNS setup instructions
- QR code generation for device onboarding

**Platform**
- Windows 10/11 and macOS (Intel + Apple Silicon)
- System tray — keeps running after window close
- Windows Service registration for headless operation (requires admin)
- PyInstaller build scripts for both platforms

---

## Requirements

**Runtime**
- Python 3.10 or later
- The app downloads PostgreSQL binaries (~150 MB) on first launch if they are not bundled

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

**Build-only** (for creating distributable packages)
- Windows: Inno Setup 6 (optional, for producing a Setup.exe installer)
- macOS: Homebrew + `create-dmg` (optional, for producing a .dmg)

---

## Installation

### Windows

**Option A — Pre-built installer**

Download `PGOps-Setup-x.x.x-Windows.exe` and run it. No admin rights required for a user-profile install; admin rights are only needed if you choose "Install for all users."

**Option B — Run from source**

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

### From the .app bundle (macOS)

Double-click `PGOps.app`. On first launch macOS may show a Gatekeeper warning; right-click → Open to proceed.

---

## First Launch

1. **Set a master password.** PGOps asks you to create a password the first time it starts. This protects access to the app and is separate from your database credentials. The hash is stored in the app data directory and never sent anywhere.

2. **Start the server.** Click **▶ START SERVER** on the Server tab. If PostgreSQL binaries are not present, click **Setup PostgreSQL** first. The app downloads and extracts them automatically.

3. **Connect.** The connection string is shown in the Connection Details card. The default credentials are:

   | Field | Default |
   |-------|---------|
   | Host | your LAN IP or `pgops.local` |
   | Port | `5432` |
   | Username | `postgres` |
   | Password | `postgres` |
   | Database | `mydb` |

   Change these in **Settings** before initialising the cluster if you want different defaults. Changing them after initialisation requires stopping the server and deleting the `pgdata` folder to reinitialise.

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

Both scripts install dependencies from `requirements.txt` and launch `main.py`. The application data directory in dev mode is the same as in production (the user's `AppData/PGOps` or `~/Library/Application Support/PGOps`).

---

## Building for Distribution

### Windows

```bat
build_windows.bat
```

Produces:
- `dist\PGOps\PGOps.exe` — standalone portable build
- `dist\installer\PGOps-Setup-1.0.0-Windows.exe` — Inno Setup installer (if Inno Setup is present)

**Bundling PostgreSQL binaries (optional)**

Download the Windows binary ZIP from EnterpriseDB, save it as `assets\pg_windows.zip`, and rebuild. The app will extract from the bundle instead of downloading at runtime.

### macOS

```bash
./build_mac.sh
```

Produces:
- `dist/PGOps.app` — app bundle
- `dist/installer/PGOps-1.0.0-macOS.dmg` — drag-to-install disk image (requires Homebrew + `create-dmg`)

**Bundling PostgreSQL binaries (optional)**

Save the macOS binary ZIP as `assets/pg_mac.zip` and rebuild.

### CLI binary

The `pgops.spec` file builds the `pgops` CLI as a separate one-file executable alongside the main app. It is included automatically when running either build script.

---

## Architecture Overview

```
PGOps Application
├── PostgreSQL 16          — managed via pg_ctl / initdb subprocess calls
├── MinIO                  — started as a child process, controlled via mc CLI
├── pgAdmin 4              — started as a child process via its bundled Python
├── Caddy                  — reverse proxy, config regenerated from apps.json
├── FrankenPHP             — one process per deployed Laravel app
├── DNS Server             — dnslib UDP server, resolves *.pgops.local → host IP
├── mDNS Broadcaster       — zeroconf, publishes pgops.local on the LAN
├── Landing Server         — tiny stdlib HTTP server on port 8080 (pgops.local root)
├── API Server             — stdlib HTTP server on 127.0.0.1:7420 (CLI target)
└── Backup Scheduler       — daemon thread, runs pg_dump on a cron-like schedule
```

**Source layout**

```
main.py                     Entry point, auth gate, window launch
pgops_cli.py                CLI tool (talks to the API server)
pgops.spec                  PyInstaller spec for both main app and CLI
requirements.txt

src/
  core/
    auth.py                 Master password hashing and verification
    config.py               App configuration load/save
    pg_manager.py           PostgreSQL binary management and cluster lifecycle
    db_manager.py           Database and role operations (create, drop, backup)
    minio_manager.py        MinIO binary management and server lifecycle
    bucket_manager.py       MinIO bucket and access-key operations via mc CLI
    pgadmin_manager.py      pgAdmin 4 process management and credential reset
    caddy_manager.py        Caddyfile generation and Caddy process control
    frankenphp_manager.py   FrankenPHP binary setup and per-app process management
    app_manager.py          App registry (apps.json), provisioning, git pull, deletion
    api_server.py           Internal REST API (127.0.0.1:7420)
    landing_server.py       pgops.local root landing page
    dns_server.py           dnslib DNS server thread
    mdns.py                 zeroconf mDNS broadcaster
    network_info.py         Network interface discovery and classification
    hotspot.py              Windows Mobile Hotspot control via PowerShell / WinRT
    scheduler.py            Automated backup scheduler
    service_manager.py      Windows Service registration via pg_ctl and sc.exe
    ssl_manager.py          Self-signed TLS certificate generation and postgresql.conf management

  ui/
    main_window.py          Root window, wires everything together
    sidebar.py              Navigation sidebar
    header_bar.py           Top header bar with breadcrumb and search
    login_dialog.py         Login, setup, and change-password dialogs
    tab_server.py           Server controls, connection details, pgAdmin/Caddy/FrankenPHP cards
    tab_activity.py         Live activity monitor
    tab_databases.py        Database list, table browser, SQL runner
    tab_apps.py             Laravel app deployment wizard and management
    tab_backup.py           Backup and restore UI
    tab_schedule.py         Backup scheduler configuration
    tab_ssl.py              SSL/TLS certificate management
    tab_service.py          Windows Service control
    tab_network.py          Network interfaces, mDNS, hotspot
    tab_dns.py              DNS server status and client setup instructions
    tab_settings.py         App settings
    files_tab.py            MinIO bucket management
    activity_monitor.py     (legacy, superseded by tab_activity.py)
    table_browser.py        (legacy, superseded by tab_databases.py)
    widgets.py              Shared UI components
    theme.py                Colour tokens and global stylesheet

assets/                     Optional pre-bundled binaries placed here before building
  pg_windows.zip            PostgreSQL Windows binaries
  pg_mac.zip                PostgreSQL macOS binaries
  minio.exe / minio         MinIO server binary
  mc.exe / mc               MinIO client binary
  caddy.exe / caddy         Caddy binary
  frankenphp.zip / frankenphp_mac   FrankenPHP binary

installer/
  windows.iss               Inno Setup script
  mac/build_dmg.sh          create-dmg wrapper
  mac/dmg_background.png    (optional) DMG background image
```

---

## User Interface

Navigation is on the left sidebar. Tabs in the upper group are the main day-to-day tools; tabs below the separator are infrastructure and advanced settings.

| Tab | Purpose |
|-----|---------|
| **Servers** | Start/stop PostgreSQL, MinIO, pgAdmin, Caddy, FrankenPHP. View connection details. |
| **Activity** | Live dashboard: connections, DB sizes, cache hit ratio, uptime, TPS. |
| **Databases** | Create/drop isolated databases, browse tables, run SQL. |
| **Apps** | Deploy and manage Laravel applications. |
| **Explorer** | SQL runner and schema browser for any connected database. |
| **Storage** | MinIO bucket creation, credential management, backup. |
| **Settings** | Change PostgreSQL credentials, port, autostart. |
| **Backup** | Manual and restore operations. |
| **Schedule** | Configure automated backup schedule and retention. |
| **SSL / TLS** | Generate self-signed certificate, enable/disable SSL in PostgreSQL. |
| **Service** | Register/remove PostgreSQL as a Windows background service. |
| **Network** | Interface list, IP pinning, mDNS control, Windows hotspot. |
| **DNS** | DNS server control and per-platform client setup instructions. |
| **Log** | Full application log output. |

---

## CLI Tool

The `pgops` CLI communicates with a running PGOps instance via the internal API on `127.0.0.1:7420`.

```bash
# Check status
pgops status

# List deployed apps
pgops apps

# Deploy from a ZIP
pgops deploy --zip ./myapp.zip --name inventory --display "Inventory Manager"

# Deploy from Git
pgops deploy --git https://github.com/org/myapp.git --name inventory --branch main

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

PGOps must be running for CLI commands to work.

---

## Configuration

Settings are saved to `config.json` in the app data directory. You can edit them through the **Settings** tab or directly in the file.

| Key | Default | Description |
|-----|---------|-------------|
| `username` | `postgres` | PostgreSQL admin username |
| `password` | `postgres` | PostgreSQL admin password |
| `database` | `mydb` | Default database name |
| `port` | `5432` | PostgreSQL port |
| `autostart` | `false` | Start PostgreSQL automatically on app launch |
| `preferred_ip` | `""` | Pinned host IP (empty = auto-detect) |
| `caddy_http_port` | `8088` | Port Caddy listens on (use 80 if you have admin/root) |
| `landing_port` | `8080` | Port the landing page server listens on |

**Changing credentials after first start** requires stopping the server and deleting the `pgdata` directory, because PostgreSQL's `initdb` bakes the superuser password into the cluster during initialisation.

---

## Data & File Locations

All mutable data is written to the user's writable app data directory — never into `Program Files` or the app bundle.

| Platform | Path |
|----------|------|
| Windows | `%LOCALAPPDATA%\PGOps\` |
| macOS | `~/Library/Application Support/PGOps/` |

Inside that directory:

```
config.json             App settings
auth.json               Master password hash
pgsql/                  PostgreSQL binaries (extracted from bundle or downloaded)
pgdata/                 PostgreSQL cluster data
postgres.log            PostgreSQL server log
backups/                pg_dump backup files
backup_schedule.json    Scheduler configuration
ssl/                    Generated TLS certificate and key
minio-bin/              MinIO and mc binaries
minio-data/             MinIO object storage data
pgadmin4-data/          pgAdmin 4 SQLite database and session files
caddy/                  Caddy binary and generated Caddyfile
frankenphp/             FrankenPHP binary
apps/                   Deployed app source files
apps.json               App registry
```

**Uninstalling:** The Windows uninstaller removes the application binaries but deliberately leaves the data directory intact so your databases and files are preserved. Delete `%LOCALAPPDATA%\PGOps` manually to remove all data.

---

## Security

### Master Password

The master password is hashed with bcrypt (12 rounds) if the `bcrypt` package is available, or PBKDF2-HMAC-SHA256 (300,000 iterations) as a fallback. The hash is stored in `auth.json`. The password is never stored in plaintext anywhere.

After five consecutive failed login attempts, the error message prompts the user to use the "Forgot password?" flow, which explains how to delete `auth.json` to reset.

To reset your password manually, delete or edit `auth.json` in the app data directory and relaunch PGOps. Your databases and data are unaffected.

### Database Credentials

PostgreSQL is configured with `md5` authentication for all connections (`pg_hba.conf`). The admin password is only written to disk temporarily during `initdb` (in a `.pwfile` that is deleted immediately after).

### MinIO Access Keys

Each bucket gets a dedicated IAM-style access key with a policy scoped to that bucket only. Other buckets are unreachable with that key. Secrets are shown once at creation time and are not stored by PGOps after that point.

### API Server

The internal REST API binds exclusively to `127.0.0.1:7420` and is not reachable from the LAN.

---

## Network & DNS

### mDNS (pgops.local)

PGOps broadcasts itself as `pgops.local` using mDNS (Zeroconf). On most platforms this works without any configuration:

- Windows 10/11: native support
- macOS / iOS: native support
- Linux: requires `avahi-daemon`
- Older Windows: install Apple Bonjour

### DNS Server

For devices where mDNS does not work (Android, some corporate networks), PGOps runs a DNS server that resolves `*.pgops.local` to the host IP. Point any device's DNS to the PGOps host IP and all subdomains resolve automatically.

The DNS server tries to bind to port 53. If that fails due to insufficient privileges it falls back to port 5353. The DNS tab shows the active port and per-platform setup instructions, including a QR code linking to `http://pgops.local` for easy device onboarding.

### Windows Hotspot

The Network tab can start and stop a Windows Mobile Hotspot using the WinRT `NetworkOperatorTetheringManager` API. If that API is unavailable on the system, PGOps opens the Windows hotspot settings page as a fallback.

The hotspot IP (`192.168.137.1`) is a fixed Windows address. PGOps detects it automatically and can pin it as the preferred host IP so connection strings remain stable.

### Firewall

On Windows you may need to allow inbound TCP on the PostgreSQL port. The Network tab shows the exact `netsh` command to run once as Administrator:

```
netsh advfirewall firewall add rule name="PGOps" dir=in action=allow protocol=TCP localport=5432
```

---

## SSL / TLS

PGOps can generate a self-signed RSA-2048 certificate valid for 10 years using the `cryptography` Python package (no OpenSSL binary required).

The certificate includes Subject Alternative Names for `pgops.local`, `localhost`, `127.0.0.1`, and the current LAN IP.

**Enable SSL:**
1. Go to the **SSL / TLS** tab.
2. Click **Generate New Certificate**.
3. Click **Enable SSL**.
4. Restart the PostgreSQL server.

Clients can then connect with `sslmode=require`. For certificate verification, export `server.crt` and distribute it to clients; use `sslmode=verify-ca` and point the client at the certificate.

**Laravel .env:**
```
DB_SSLMODE=require
```

**psycopg2:**
```python
psycopg2.connect(..., sslmode='require')
```

---

## Scheduled Backups

The **Schedule** tab configures automatic `pg_dump` backups running in a background thread.

| Setting | Options |
|---------|---------|
| Frequency | Hourly, Daily, Weekly |
| Time | HH:MM (for daily/weekly) |
| Day of week | Monday–Sunday (for weekly) |
| Keep last N | Number of backup files to retain per database |
| Databases | Checkboxes for each managed database |

Backup files are saved to the `backups/` directory in the app data folder in PostgreSQL custom format (`.dump`). They can be restored through the **Backup** tab or directly with `pg_restore`.

---

## Windows Service Mode

The **Service** tab registers PostgreSQL as a Windows background service using `pg_ctl register`. In service mode, PostgreSQL starts automatically at system boot before any user logs in.

**Requires:** PGOps must be run as Administrator to install or remove the service.

The service is named `PGOps-PostgreSQL` and is set to auto-start. PGOps itself still runs in app mode and communicates with the service-managed PostgreSQL instance the same way it does with a process-managed one.

---

## Deploying Laravel Apps

Apps are deployed through the **Apps** tab using the Deploy Wizard.

**What the wizard does:**
1. Extracts the ZIP or clones the Git repository into the `apps/<slug>/` folder.
2. Creates an isolated PostgreSQL database and owner role.
3. Creates a MinIO bucket with a dedicated access key.
4. Writes a `.env` file with all connection details pre-filled.
5. Runs `php artisan key:generate`.
6. Runs `php artisan migrate --force`.
7. Starts a FrankenPHP process serving the app on an internal port.
8. Reloads Caddy so `<slug>.pgops.local` routes to the app.

**Requirements:**
- FrankenPHP binary must be set up first (click **Setup FrankenPHP** on the Server tab).
- Caddy binary must be set up first (click **Setup Caddy** on the Server tab).
- The DNS server or mDNS must be running so `<slug>.pgops.local` resolves on client devices.

**App management:**
- Start, stop, restart individual apps from the Apps tab.
- Stream live logs.
- Pull latest from Git, run migrations, and restart in one click.
- Delete an app — this drops the database, removes the bucket, and deletes all files.

**The CLI** provides the same operations for scripting:
```bash
pgops deploy --git https://github.com/org/app.git --name myapp
pgops pull myapp
pgops logs myapp --lines 100
pgops delete myapp
```

---

## MinIO Storage

The **Storage** tab manages MinIO object storage.

**Setup:** Click **Setup MinIO** on the Storage tab (or Server tab) to download the MinIO and mc binaries. Then click **▶ Start Storage**.

**Buckets:** Each bucket gets an isolated access key with a policy allowing only that bucket. The secret is shown once at creation time. Use **Rotate Keys** to generate new credentials if needed.

**Connecting from Laravel:**
```
FILESYSTEM_DISK=s3
AWS_ACCESS_KEY_ID=<access_key>
AWS_SECRET_ACCESS_KEY=<secret_key>
AWS_DEFAULT_REGION=us-east-1
AWS_BUCKET=<bucket_name>
AWS_ENDPOINT=http://pgops.local:9000
AWS_USE_PATH_STYLE_ENDPOINT=true
```

The MinIO web console is available at `http://<host_ip>:9001`. Use the admin username and password from your PGOps settings (same as PostgreSQL admin credentials by default).

**Note:** Use the direct IP address for the MinIO console URL rather than `pgops.local` — browsers may enforce HTTPS on `.local`/`.local` domains via HSTS, which breaks plain HTTP connections.

---

## Troubleshooting

**PostgreSQL fails to start**

Check the **Log** tab. Common causes:
- Port 5432 already in use by another PostgreSQL instance. Change the port in Settings.
- The `pgdata` directory is corrupt. Stop the server, back up and delete `pgdata/`, restart (this reinitialises the cluster and loses all data).

**pgAdmin shows a blank screen or login fails**

Click **Reset & Restart** on the Server tab. This deletes pgAdmin's SQLite database and restarts it fresh. The default credentials are `admin@pgops.com` / `pgopsadmin`.

**pgops.local does not resolve**

- Ensure the mDNS broadcaster is running (green status on the Network tab).
- On Windows, make sure the Windows Firewall allows UDP on port 5353.
- On Android, use the DNS server approach instead of mDNS: point the device DNS to the PGOps host IP.
- Check the DNS tab — if the DNS server is running on port 5353 instead of 53, you need admin/root privileges or must configure the client to use a non-standard DNS port.

**Caddy / apps not reachable from other devices**

- Ensure the DNS server or mDNS is working on the client device.
- Check that `caddy_http_port` is set to `80` (requires admin) or that your client is using the correct port.
- On Windows, add a firewall rule for the Caddy port.

**MinIO console opens but shows a connection error**

Use the direct IP address (`http://192.168.x.x:9001`) rather than `pgops.local:9001`. Browsers enforce HTTPS on `.local` domains, breaking HTTP connections to the console.

**Master password forgotten**

Delete `auth.json` from the app data directory (`%LOCALAPPDATA%\PGOps\auth.json` on Windows, `~/Library/Application Support/PGOps/auth.json` on macOS) and relaunch PGOps. You will be prompted to set a new password. Your databases and data are not affected.

**App deployment fails at artisan migrate**

Check that PostgreSQL is running and that the database was created successfully. The Log tab will show the artisan output. Common causes are missing PHP extensions in the FrankenPHP build or a missing `.env` value.

---

## License

See `LICENSE` for details.