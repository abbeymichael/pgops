


<img width="1600" height="1280" alt="dashboard" src="https://github.com/user-attachments/assets/f574541f-e0f6-4da5-8431-fb340ee61f32" />

<img width="1600" height="1471" alt="screen" src="https://github.com/user-attachments/assets/903f8817-0174-40c3-a751-08ddd05be91b" />

<img width="1600" height="1292" alt="activity" src="https://github.com/user-attachments/assets/db1cfb72-df5e-48ff-b173-54cb4dddc63e" />

# PGOps — Documentation
**PGOps** is a portable, self-contained server management application for Windows and macOS.
It provides a local area network (LAN) infrastructure layer for desktop and web applications
built with frameworks like Laravel and NativePHP — handling database hosting, file storage,
network discovery, SSL encryption, backups, and activity monitoring from a single interface.

No cloud subscription. No internet dependency. No IT department required.

---

## Table of Contents

1. [What PGOps Is](#1-what-pgops-is)
2. [System Requirements](#2-system-requirements)
3. [Installation](#3-installation)
4. [First Launch](#4-first-launch)
5. [Security — App Password](#5-security--app-password)
6. [Server Tab — PostgreSQL](#6-server-tab--postgresql)
7. [Activity Monitor Tab](#7-activity-monitor-tab)
8. [Databases Tab](#8-databases-tab)
9. [Table Browser Tab](#9-table-browser-tab)
10. [Backup & Restore Tab](#10-backup--restore-tab)
11. [Files Tab — MinIO Object Storage](#11-files-tab--minio-object-storage)
12. [Schedule Tab](#12-schedule-tab)
13. [SSL / TLS Tab](#13-ssl--tls-tab)
14. [Service Tab — Windows Service Mode](#14-service-tab--windows-service-mode)
15. [Settings Tab](#15-settings-tab)
16. [Network Tab](#16-network-tab)
17. [Local Domain — pgops.local](#17-local-domain--pgopslocal)
18. [Connecting Laravel Applications](#18-connecting-laravel-applications)
19. [Connecting Other Frameworks](#19-connecting-other-frameworks)
20. [Data Locations](#20-data-locations)
21. [Building from Source](#21-building-from-source)
22. [Deployment Scenarios](#22-deployment-scenarios)
23. [Troubleshooting](#23-troubleshooting)

---

## 1. What PGOps Is

PGOps runs two servers on a single machine and makes them accessible to every device
on the same network:

- **PostgreSQL 16** — relational database server (port 5432)
- **MinIO** — S3-compatible object storage server (port 9000, console port 9001)

Both are bundled as portable binaries. Neither requires a separate installation.
Both are accessible via the hostname `pgops.local` which PGOps broadcasts
automatically using mDNS — so connected apps never need a hardcoded IP address.

### Who it is for

- Developers building Laravel or NativePHP desktop applications for small organisations
- Teams that need a shared database and file storage on a local network
- Organisations in low-connectivity environments where cloud services are unreliable
- Any setup where a dedicated VM or mini PC acts as a local application server

### What it is not

PGOps is not a replacement for production cloud infrastructure. It is designed for
organisations with 1–20 concurrent users on a local network, where data stays on-premise
and internet connectivity cannot be guaranteed.

---

## 2. System Requirements

### Host machine (where PGOps runs)

| Item | Requirement |
|---|---|
| OS | Windows 10/11 (64-bit) or macOS 11+ |
| RAM | 2 GB minimum, 4 GB recommended |
| Disk | 500 MB for binaries + space for your data |
| Network | Ethernet or Wi-Fi — must be on the same network as client devices |

### Client devices (apps connecting to PGOps)

- Any device on the same LAN or connected to the PGOps hotspot
- No software installation required on clients
- mDNS support required for `pgops.local` hostname resolution (see Section 17)

---

## 3. Installation

### Windows

1. Run `PGOps-Setup-1.0.0-Windows.exe`
2. Follow the installer — no admin rights required for a user-level install
3. Optional: tick "Start PGOps when Windows starts" for automatic launch
4. Launch PGOps from the Start Menu or Desktop shortcut

### macOS

1. Open `PGOps-1.0.0-macOS.dmg`
2. Drag `PGOps.app` to your Applications folder
3. Launch from Applications

### Building from source

See Section 21.

---

## 4. First Launch

### Step 1 — Set your app password

On the very first launch, PGOps shows a setup screen asking you to create a master password.
This password protects access to the PGOps interface. It has nothing to do with your
database or storage credentials. Minimum 4 characters.

### Step 2 — Setup PostgreSQL binaries

If PostgreSQL binaries are not bundled in your installer, the Server tab shows a
"Setup PostgreSQL" button. Click it to download the portable PostgreSQL 16 binaries
(approximately 150 MB, one time only). If binaries are bundled, this step is skipped.

### Step 3 — Start the server

Click **Start Server** on the Server tab. PGOps will:

- Initialise the PostgreSQL cluster on first run
- Configure it to listen on all network interfaces
- Configure `pg_hba.conf` to allow LAN connections
- Create the default database
- Start broadcasting `pgops.local` on the network

### Step 4 — Connect your apps

Use the connection details shown on the Server tab. For new app-specific databases,
go to the Databases tab and create a dedicated database with its own user.

---

## 5. Security — App Password

PGOps is protected by a master password shown on every launch.

### Login screen

Enter your password to unlock PGOps. After 5 incorrect attempts the error message
updates to reflect the number of failures. The window shakes on wrong attempts.

### Forgot password

Click "Forgot password?" on the login screen. You will be shown the path to the
`auth.json` file. Delete that file and relaunch PGOps — the setup screen appears
again to create a new password. Your databases and files are not affected.

**Windows path:**
```
%LOCALAPPDATA%\PGOps\auth.json
```

**macOS path:**
```
~/Library/Application Support/PGOps/auth.json
```

### Change password

Go to **Settings → App Password → Change Password**. You must enter the current
password before setting a new one.

### How the password is stored

Passwords are hashed using bcrypt (rounds=12) and stored in `auth.json`.
The plaintext password is never written to disk.

---

## 6. Server Tab — PostgreSQL

The Server tab is the main control panel for PostgreSQL.

### Controls

| Button | Action |
|---|---|
| Start Server | Initialises (first run) and starts PostgreSQL |
| Stop Server | Gracefully stops PostgreSQL using `pg_ctl stop -m fast` |
| Setup PostgreSQL | Downloads or extracts portable binaries (one time) |

### Connection details

Once the server is running, the Server tab displays:

| Field | Default | Description |
|---|---|---|
| Host | Your LAN IP | The IP address clients use to connect |
| Port | 5432 | PostgreSQL port |
| Username | postgres | Admin username |
| Password | postgres | Admin password |
| Database | mydb | Default database |
| String | Full URL | Complete PostgreSQL connection string |

Every field has a **Copy** button. The connection string format is:
```
postgresql://username:password@host:5432/database
```

### System tray

Closing the PGOps window does not stop the server. PGOps minimises to the system tray
and continues running. Double-click the tray icon to restore the window. Right-click
for a menu with Start Server, Stop Server, and Quit options.

---

## 7. Activity Monitor Tab

The Activity Monitor shows live statistics about the running PostgreSQL server.
It refreshes automatically every 5 seconds when the tab is visible and pauses
when you switch to another tab to avoid unnecessary load.

### Stat cards

| Card | Description |
|---|---|
| Active Connections | Number of connections currently executing queries |
| Total Databases | Number of user databases on this server |
| Cache Hit Ratio | Percentage of data served from memory vs disk |
| Uptime | Time since PostgreSQL was last started |
| Transactions/s | Average transaction rate since last stats reset |

### Active connections table

Shows every current connection with:

- **PID** — PostgreSQL process ID
- **Database** — which database the connection is using
- **User** — the role/user that connected
- **Application** — application name reported by the client
- **State** — connection state, colour-coded: green (active), amber (idle in transaction), grey (idle)
- **Duration** — how long the current query has been running

### Terminate connection

Select a row and click **Terminate Selected Connection** to send `pg_terminate_backend()`
to that process. A confirmation dialog appears first. The client application will receive
a disconnection error.

### Database sizes table

Lists every database with its total size on disk, active connection count, and
cache hit percentage. Cache hit is colour-coded: green (≥90%), amber (≥70%), red (<70%).
A low cache hit ratio suggests the server needs more RAM.

---

## 8. Databases Tab

The Databases tab manages multiple PostgreSQL databases, each with its own owner
username and password. This is the correct way to isolate different applications
from each other — each app gets its own database and credentials.

### Creating a database

Click **New Database**. Fill in:

- **Database Name** — the database identifier (no spaces)
- **Owner Username** — the role that owns and controls this database
- **Owner Password** — the password for that role (confirm it)

PGOps creates the role (if it does not already exist), creates the database owned
by that role, and grants full privileges including:

- `GRANT ALL PRIVILEGES ON DATABASE` — connect and create objects
- `GRANT ALL ON SCHEMA public` — access the public schema
- `GRANT ALL ON ALL TABLES` — access existing tables
- `GRANT ALL ON ALL SEQUENCES` — access sequences (required for auto-increment inserts)
- `ALTER DEFAULT PRIVILEGES` — ensures future tables created by migrations are also accessible
- `ALTER SCHEMA public OWNER TO` — full schema ownership

This means Laravel migrations run as the admin user will produce tables that are
immediately accessible to the app user — no manual `GRANT` statements needed.

### Connection string format

The Databases table shows a connection string for each database:
```
postgresql://owner:<password>@192.168.x.x:5432/database_name
```

Replace `<password>` with the owner's actual password.

### Dropping a database

Select a row and click **Drop Selected**. A confirmation dialog warns that this
action is permanent. Active connections to the database are terminated before dropping.

### Changing a password

Select a row and click **Change Password**. Enter the new password twice to confirm.
This runs `ALTER ROLE ... WITH PASSWORD` on the PostgreSQL server.

---

## 9. Table Browser Tab

The Table Browser provides a graphical interface for browsing and querying any database
on the server. All database operations run in background threads — the UI never freezes.

### Connecting

Select a database from the dropdown and click **Connect**. PGOps connects using the
admin credentials from Settings. Once connected, the schema tree loads automatically.

### Schema tree

The left panel shows all schemas in the selected database, with tables and views
grouped separately. Click any table or view to load its data.

### Data grid

- Displays the first 100 rows by default
- **Prev / Next** buttons paginate through large tables
- Row count and total are shown in the bottom bar
- NULL values are displayed in grey italic

### SQL runner

The bar at the top accepts any SQL query. Press Enter or click **Run** to execute.
Results appear in the data grid. For non-SELECT statements (INSERT, UPDATE, DELETE,
CREATE, etc.) the affected row count is shown. Errors appear as a red message in the grid.

Clicking a table in the schema tree pre-fills the SQL bar with `SELECT * FROM table`.

### Refresh Schema

Click **Refresh Schema** to reload the schema tree after running migrations or
making structural changes.

---

## 10. Backup & Restore Tab

### Backup

PGOps uses `pg_dump` in custom format (`.dump` files) which are compressed and
support selective restore.

1. Select a database from the dropdown
2. Optionally change the destination folder (default: `%LOCALAPPDATA%\PGOps\backups\`)
3. Click **Backup Now**

The backup button is disabled during the operation to prevent double-triggers.
A progress bar shows the operation status. The backup file is named:
```
databasename_YYYYMMDD_HHMMSS.dump
```

### Restore

1. Select a backup from the list (sorted newest first) or click **Open File** to browse
2. Enter the target database name (existing or new — PGOps creates it if needed)
3. Click **Restore Selected Backup**

Restore uses `pg_restore` with `--clean` (drops existing objects before restoring)
and `--no-owner` (objects are owned by the restoring user).

A confirmation dialog appears before restore begins. The restore button is disabled
during the operation.

### Backup list

The list shows all `.dump` files in the backup directory with filename, size in MB,
and creation timestamp, sorted newest first.

---

## 11. Files Tab — MinIO Object Storage

PGOps includes MinIO, an S3-compatible object storage server. Laravel applications
use the standard `s3` filesystem driver — no custom code required.

### Ports

| Service | Port | Purpose |
|---|---|---|
| MinIO API | 9000 | File operations (S3 protocol) |
| MinIO Console | 9001 | Web-based admin interface |

### Starting the storage server

Click **Start Storage** in the Files tab header. MinIO starts automatically alongside
PostgreSQL when you click Start Server on the Server tab (if binaries are available).

If MinIO binaries are not installed, click **Download MinIO** to fetch them. You can
also bundle `minio.exe` and `mc.exe` in the `assets/` folder before building to avoid
the download entirely.

### Web Console

Click **Open Web Console** to open the MinIO admin interface in your browser at
`http://pgops.local:9001`. Log in with the admin username and password from Settings
(default: `postgres` / `postgres`).

### Creating a bucket

Click **New Bucket**. Fill in:

- **Bucket Name** — lowercase, 3–63 characters, hyphens allowed, no spaces
- **App / Label** — optional prefix for the generated access key

PGOps automatically:

1. Creates the bucket
2. Generates a unique access key ID and secret key
3. Creates a bucket-scoped IAM policy that restricts this key to this bucket only
4. Attaches the policy to the access key

A credentials dialog appears immediately showing:

- Bucket name
- Access Key ID
- Secret Key (shown once — save it now)
- Full Laravel `.env` block ready to copy and paste

**The secret key cannot be retrieved after this dialog closes.** Use Rotate Keys
to generate new credentials if you lose the secret.

### Bucket isolation

Each bucket's access key is restricted by an IAM policy to that bucket only.
An app using bucket `app1-files` cannot read or write to `app2-files`, even if it
has the correct endpoint and port.

### Rotate Keys

Select a bucket and click **Rotate Keys**. The old access key is immediately deleted
and new credentials are generated. A credentials dialog shows the new key and secret.
Update your Laravel `.env` files after rotating.

### Drop Bucket

Select a bucket and click **Drop Selected**. This permanently deletes:

- All files in the bucket
- The bucket itself
- The associated access key and policy

A confirmation dialog warns that this is irreversible.

### Backup a bucket

Select a bucket and click **Backup Bucket**. Choose a destination folder.
PGOps uses `mc mirror` to copy all files to a local directory named after the bucket.

### Laravel configuration

After creating a bucket, add this to your Laravel `.env`:

```env
FILESYSTEM_DISK=s3
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-1
AWS_BUCKET=your-bucket-name
AWS_ENDPOINT=http://pgops.local:9000
AWS_USE_PATH_STYLE_ENDPOINT=true
```

And ensure your `config/filesystems.php` has the `s3` disk configured (it does by default
in all Laravel installations).

Files stored via `Storage::put()`, `Storage::disk('s3')->put()`, or any standard
Laravel storage call will be saved to MinIO and accessible to all devices on the network.

---

## 12. Schedule Tab

The Schedule tab configures automatic backups that run in the background without
any user interaction.

### Configuration

| Setting | Options | Description |
|---|---|---|
| Enable | On/Off | Master switch for scheduled backups |
| Frequency | Hourly, Daily, Weekly | How often backups run |
| At time | HH:MM | Time of day for daily/weekly backups |
| Day | Monday–Sunday | Day of week for weekly backups |
| Keep last N | 1–365 | Number of backups to retain per database |

### Database selection

The database list shows all current databases with a checkbox. Only checked databases
are included in scheduled backups.

### Pruning

After each scheduled backup, PGOps automatically deletes the oldest backup files
for each database, keeping only the most recent N copies as configured.

### Next run

The Schedule tab and the 3-second poll timer both display the calculated next run time
based on the current schedule configuration.

### Background operation

The scheduler runs in a daemon thread. It checks every 60 seconds whether a backup
is due. It does not wake the machine from sleep — if the machine is asleep at the
scheduled time, that backup is skipped and the next one runs on schedule.

---

## 13. SSL / TLS Tab

PGOps can encrypt all database connections on the LAN using TLS.

### Certificate generation

Click **Generate New Certificate**. PGOps uses the `cryptography` Python library
to create a self-signed RSA 2048-bit certificate valid for 10 years. The certificate
covers:

- `pgops.local`
- `localhost`
- `pgops`
- `127.0.0.1`
- Your current LAN IP at the time of generation
- `192.168.137.1` (hotspot IP)

The certificate is saved to `%LOCALAPPDATA%\PGOps\ssl\server.crt` and the private
key to `server.key`.

### Enabling SSL

Click **Enable SSL**. PGOps copies the certificate and key into the PostgreSQL data
directory and updates `postgresql.conf` with:

```
ssl = on
ssl_cert_file = 'server.crt'
ssl_key_file  = 'server.key'
```

**Restart the server after enabling SSL** for the change to take effect.

### Disabling SSL

Click **Disable SSL**. PGOps sets `ssl = off` in `postgresql.conf`. Restart the
server to apply.

### Exporting the certificate

Click **Export server.crt** to save a copy of the certificate to any location.
Distribute this file to client machines that use `sslmode=verify-ca` — they need
the certificate to verify the server's identity.

### Connecting with SSL

| sslmode | Behaviour |
|---|---|
| `require` | Encrypts the connection, does not verify the certificate |
| `verify-ca` | Encrypts and verifies the certificate (requires server.crt on client) |

For most LAN deployments, `sslmode=require` is sufficient.

**Laravel `.env`:**
```env
DB_SSLMODE=require
```

**psycopg2 (Python):**
```python
psycopg2.connect(..., sslmode='require')
```

**Connection URL:**
```
postgresql://user:pass@pgops.local:5432/dbname?sslmode=require
```

---

## 14. Service Tab — Windows Service Mode

By default, PGOps requires someone to be logged in and the app to be running
for the database to be available. Service Mode removes this requirement.

### What service mode does

Registering PostgreSQL as a Windows service means it:

- Starts automatically when the PC boots, before anyone logs in
- Continues running after users log out
- Is managed by Windows Service Control Manager (SCM)
- Survives PGOps being closed entirely

This is the recommended mode for dedicated VMs and mini PCs acting as servers.

### Installing the service

**Requires running PGOps as Administrator.**

Click **Install Service**. PGOps runs `pg_ctl register` to register the service as
`PGOps-PostgreSQL` with automatic startup. The service display name is
`PGOps PostgreSQL Server`.

If you are not running as Administrator, a warning explains how to relaunch with
the required privileges.

### Service controls

| Button | Action |
|---|---|
| Install Service | Registers PostgreSQL as a Windows auto-start service |
| Remove Service | Stops and unregisters the service |
| Start Service | Starts the service via `sc start` |
| Stop Service | Stops the service via `sc stop` |

### Service vs app mode

| Mode | Best for |
|---|---|
| App mode (tray icon) | Personal PCs where someone is always logged in |
| Service mode | Dedicated VMs, mini PCs, always-on server machines |

When running as a service, PGOps is still useful for administration — the database
keeps running even when you close the PGOps window entirely.

---

## 15. Settings Tab

### Server configuration

| Setting | Default | Description |
|---|---|---|
| Admin Username | postgres | PostgreSQL superuser username |
| Admin Password | postgres | PostgreSQL superuser password |
| Default Database | mydb | Database created on first start |
| Port | 5432 | PostgreSQL listening port |
| Auto-start | Off | Start PostgreSQL automatically when PGOps opens |

**Important:** Changing admin credentials requires stopping the server and deleting
the `pgdata/` folder to reinitialise the cluster. Existing data will be lost unless
you back it up first.

### App password

The Change Password section lets you update the master password used to unlock PGOps.
You must enter the current password before setting a new one.

---

## 16. Network Tab

### Available network interfaces

PGOps scans all network adapters using `ipconfig` (Windows) or `ifconfig` (macOS)
and lists every available IPv4 address with its adapter name and type:

| Type | Colour | Description |
|---|---|---|
| Hotspot (fixed) | Green | Windows Mobile Hotspot — always 192.168.137.1 |
| Ethernet LAN | Blue | Wired connection |
| Wi-Fi | Purple | Wireless connection |
| Loopback | Grey | 127.0.0.1 — local only |

### Pinning an IP

By default, PGOps auto-detects the best IP to use as the database host (hotspot > LAN > Wi-Fi).
If your network setup causes the IP to change frequently, select a row and click
**Pin Selected** to lock the host IP. This pinned value is saved to config and used
in all connection strings.

Click **Auto-detect** to remove the pin and return to automatic selection.

### Why pin the hotspot IP

When using Windows Mobile Hotspot, the hotspot adapter always gets `192.168.137.1`.
This IP never changes. Pinning it means your apps always connect to the same address
regardless of what other network changes occur on the host machine.

### WiFi Hotspot

PGOps can create a Windows Mobile Hotspot so other devices can connect directly
to the host machine without a router.

1. Enter an SSID (network name) and password (minimum 8 characters)
2. Click **Start Hotspot**

PGOps uses the Windows Runtime (WinRT) API via PowerShell. If this fails on your
hardware, click **Open Settings** to open the Windows Mobile Hotspot settings page
directly where you can configure it manually.

Once the hotspot is active, connecting devices can reach the database at `192.168.137.1:5432`.
Pin this IP in PGOps for a permanently stable connection string.

### Firewall

For clients on a regular LAN (not hotspot) to connect, Windows Firewall must allow
inbound connections on port 5432. The Network tab shows the exact command to run
once as Administrator:

```cmd
netsh advfirewall firewall add rule name="PGOps" dir=in action=allow protocol=TCP localport=5432
```

A Copy button is provided.

---

## 17. Local Domain — pgops.local

PGOps broadcasts `pgops.local` on the network using mDNS (Multicast DNS, also known
as Zeroconf or Bonjour). This means any device on the same LAN or hotspot can resolve
`pgops.local` to the host machine's current IP address — automatically, without any
DNS server or manual configuration.

### Why this matters

Without mDNS, your apps must use an IP address as the database host. If that IP
changes (DHCP lease renewal, network change, different router), all apps break.

With `pgops.local`, the hostname never changes. Your apps use:

```
host = pgops.local
```

...and it always works, regardless of what IP the host machine currently has.

### Broadcast lifecycle

- mDNS starts broadcasting 500ms after PGOps opens — before the server even starts
- It continues broadcasting regardless of whether PostgreSQL is running or stopped
- It only stops when PGOps quits entirely
- Clicking **Stop Broadcasting** shows a warning because stopping it breaks all connected apps

### Platform support

| Platform | Support | Notes |
|---|---|---|
| Windows 10/11 | Native | Built-in mDNS — no setup needed |
| Windows 7/8 | Requires Bonjour | Install from Apple (free) |
| macOS | Native | Built-in |
| iOS | Native | Built-in |
| Android | Usually works | Most modern apps support mDNS |
| Linux | Requires avahi | `sudo apt install avahi-daemon` |

### Testing resolution

Click **Test Resolution** in the Network tab to verify that `pgops.local` resolves
correctly from the host machine itself.

### MinIO over mDNS

MinIO is also accessible at `pgops.local:9000` (API) and `pgops.local:9001` (console).
Use `pgops.local` as the endpoint in your Laravel `.env`:

```env
AWS_ENDPOINT=http://pgops.local:9000
```

---

## 18. Connecting Laravel Applications

### Database connection

```env
DB_CONNECTION=pgsql
DB_HOST=pgops.local
DB_PORT=5432
DB_DATABASE=your_database_name
DB_USERNAME=your_database_owner
DB_PASSWORD=your_database_password
DB_SSLMODE=require
```

Enable the PostgreSQL PHP extension if not already active:

In `php.ini` (Laragon: Menu → PHP → php.ini):
```ini
extension=pdo_pgsql
extension=pgsql
```

Restart your web server after enabling the extension.

### File storage connection

```env
FILESYSTEM_DISK=s3
AWS_ACCESS_KEY_ID=your_bucket_access_key
AWS_SECRET_ACCESS_KEY=your_bucket_secret_key
AWS_DEFAULT_REGION=us-east-1
AWS_BUCKET=your_bucket_name
AWS_ENDPOINT=http://pgops.local:9000
AWS_USE_PATH_STYLE_ENDPOINT=true
```

No changes to application code are needed. All `Storage::` calls work as normal.

### NativePHP desktop applications

NativePHP applications run as local processes. They connect to PGOps over the LAN
exactly like any other app — using `pgops.local` as the host. This works whether
the NativePHP app is running on the same machine as PGOps or on a different machine.

### Running migrations

```bash
php artisan migrate
```

Migrations run as the admin user (connecting via `pgops.local`) and create tables in
your app's database. The app user has full privileges on all tables created by migrations
including existing and future ones.

---

## 19. Connecting Other Frameworks

### Node.js (pg / node-postgres)

```javascript
const { Pool } = require('pg')
const pool = new Pool({
  host:     'pgops.local',
  port:     5432,
  database: 'your_database',
  user:     'your_user',
  password: 'your_password',
  ssl:      { rejectUnauthorized: false }  // for sslmode=require
})
```

### Python (psycopg2)

```python
import psycopg2
conn = psycopg2.connect(
    host='pgops.local',
    port=5432,
    dbname='your_database',
    user='your_user',
    password='your_password',
    sslmode='require'
)
```

### Python (SQLAlchemy)

```python
engine = create_engine(
    'postgresql://your_user:your_password@pgops.local:5432/your_database'
    '?sslmode=require'
)
```

### .NET / Entity Framework

```csharp
"ConnectionStrings": {
  "DefaultConnection": "Host=pgops.local;Port=5432;Database=your_database;
                        Username=your_user;Password=your_password;SSL Mode=Require"
}
```

### File storage (any S3-compatible client)

```
Endpoint:  http://pgops.local:9000
AccessKey: your_access_key
SecretKey: your_secret_key
Bucket:    your_bucket_name
PathStyle: true
Region:    us-east-1 (any value works)
```

---

## 20. Data Locations

All mutable data is stored in a user-writable directory — never inside Program Files.

### Windows

| Data | Path |
|---|---|
| PostgreSQL binaries | `%LOCALAPPDATA%\PGOps\pgsql\` |
| PostgreSQL data | `%LOCALAPPDATA%\PGOps\pgdata\` |
| PostgreSQL log | `%LOCALAPPDATA%\PGOps\postgres.log` |
| MinIO binaries | `%LOCALAPPDATA%\PGOps\minio-bin\` |
| MinIO data | `%LOCALAPPDATA%\PGOps\minio-data\` |
| Backup files | `%LOCALAPPDATA%\PGOps\backups\` |
| SSL certificates | `%LOCALAPPDATA%\PGOps\ssl\` |
| Configuration | `%LOCALAPPDATA%\PGOps\config.json` |
| Schedule | `%LOCALAPPDATA%\PGOps\backup_schedule.json` |
| Auth | `%LOCALAPPDATA%\PGOps\auth.json` |

### macOS

Replace `%LOCALAPPDATA%\PGOps\` with `~/Library/Application Support/PGOps/`.

### Resetting a database cluster

To start fresh (all data will be lost):

1. Stop the server
2. Delete `%LOCALAPPDATA%\PGOps\pgdata\`
3. Start the server — a new cluster is initialised automatically

### Uninstalling

The PGOps uninstaller removes the application files from Program Files but does
**not** delete your data directory. A message informs you of the data location
so you can delete it manually if desired.

---

## 21. Building from Source

### Prerequisites

- Python 3.11 or later
- pip

### Development run (no build)

**Windows:**
```cmd
run_dev.bat
```

**macOS:**
```bash
chmod +x run_dev.sh && ./run_dev.sh
```

### Install dependencies manually

```bash
pip install -r requirements.txt
```

Dependencies:
- `PyQt6` — desktop GUI
- `psycopg2-binary` — PostgreSQL connections (Table Browser, Activity Monitor)
- `zeroconf` — mDNS broadcasting
- `cryptography` — SSL certificate generation
- `bcrypt` — password hashing
- `requests` — binary downloads
- `pyinstaller` — packaging

### Building a Windows installer

**Prerequisites:**
- Inno Setup 6 (jrsoftware.org/isinfo.php) — for the Setup.exe wrapper

```cmd
build_windows.bat
```

Output: `dist\installer\PGOps-Setup-1.0.0-Windows.exe`

### Building a macOS DMG

**Prerequisites:**
- Homebrew
- `brew install create-dmg`

```bash
chmod +x build_mac.sh && ./build_mac.sh
```

Output: `dist/installer/PGOps-1.0.0-macOS.dmg`

### Bundling binaries (recommended)

To avoid requiring an internet connection on first launch, place these files
in `assets/` before building:

| File | Source |
|---|---|
| `assets/pg_windows.zip` | enterprisedb.com/download-postgresql-binaries — Windows x86-64 zip |
| `assets/pg_mac.zip` | enterprisedb.com/download-postgresql-binaries — macOS zip |
| `assets/minio.exe` | dl.min.io/server/minio/release/windows-amd64/minio.exe |
| `assets/mc.exe` | dl.min.io/client/mc/release/windows-amd64/mc.exe |
| `assets/minio` | dl.min.io/server/minio/release/darwin-amd64/minio |
| `assets/mc` | dl.min.io/client/mc/release/darwin-amd64/mc |

---

## 22. Deployment Scenarios

### Scenario A — Dedicated mini PC or VM (recommended)

A single low-cost machine (Intel NUC, Raspberry Pi 5, or VM) runs PGOps with
Service Mode enabled. It stays on 24/7 and serves all devices on the LAN.

Setup:
1. Install PGOps
2. Set a static LAN IP on the machine (e.g. 192.168.1.10)
3. Pin that IP in the Network tab
4. Enable Windows Service Mode
5. Enable SSL
6. All apps connect to `pgops.local:5432`

### Scenario B — Developer laptop, no router

A developer's laptop acts as the host. Other devices connect via Windows Mobile Hotspot.

Setup:
1. Start PGOps
2. Enable hotspot from the Network tab (SSID: PGOps-Net)
3. Other devices connect to PGOps-Net WiFi
4. Pin `192.168.137.1` in the Network tab
5. All apps connect to `pgops.local:5432` or `192.168.137.1:5432`

### Scenario C — Existing LAN with router

All devices are already on the same router. PGOps runs on one machine.

Setup:
1. Run the firewall command from the Network tab once as Administrator
2. Apps connect to `pgops.local:5432` — mDNS handles IP resolution automatically

---

## 23. Troubleshooting

### App won't start — "PostgreSQL binaries not found"

Click **Setup PostgreSQL** on the Server tab. If you have no internet, place the
PostgreSQL zip in `assets/pg_windows.zip` (Windows) or `assets/pg_mac.zip` (macOS)
and re-run setup.

### Can't connect from another machine

1. Run the firewall command from the Network tab as Administrator
2. Verify both machines are on the same network
3. Try connecting to the IP address directly instead of `pgops.local`
4. If using hotspot: ensure the client device joined the correct hotspot network

### pgops.local doesn't resolve on Windows clients

Windows 10/11 has built-in mDNS. If it still fails:
- Install Bonjour from Apple (free, used by iTunes)
- Or connect using the IP address shown in the Network tab instead

### pgops.local doesn't resolve on Linux clients

```bash
sudo apt install avahi-daemon
sudo systemctl enable avahi-daemon
sudo systemctl start avahi-daemon
```

### "Permission denied for table" errors

This means the database user does not have access to the tables. This happens
with databases created by older versions of PGOps. Fix by running in psql
as the admin user (connected to the affected database):

```sql
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "your_user";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "your_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "your_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "your_user";
```

Databases created by PGOps v6 and later have these grants applied automatically.

### MinIO won't start

Ensure `minio.exe` is present in `%LOCALAPPDATA%\PGOps\minio-bin\`.
Click **Download MinIO** on the Files tab to fetch it.

### Forgot app password

Delete `%LOCALAPPDATA%\PGOps\auth.json` and relaunch PGOps.
The setup screen appears to create a new password.
Databases and files are not affected.

### Server stops unexpectedly

Check `%LOCALAPPDATA%\PGOps\postgres.log` for PostgreSQL error details.
Common causes: disk full, port conflict, or the machine went to sleep.

### Port 5432 already in use

Another PostgreSQL instance may be running. Change the port in Settings
(e.g. to 5433) and restart the server. Update all app connection strings accordingly.

---

*PGOps is built with Python, PyQt6, PostgreSQL 16, and MinIO.*
*It is designed for local network deployments in small organisations.*
