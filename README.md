# PGOps — Portable PostgreSQL Server

A lightweight desktop app (Windows + macOS) that runs a self-contained PostgreSQL server
and exposes it over your LAN. No PostgreSQL installation needed.
Other apps connect using standard `host:port` credentials — exactly like Laragon's database.

---

## Quick Start

### Development (no build)

```bash
# Install deps
pip install -r requirements.txt        # Windows
pip3 install -r requirements.txt       # Mac

# Run
python main.py       # Windows
python3 main.py      # Mac
```

---

## Building Installers

### Windows → `PGOps-Setup.exe`

**Prerequisites:**
- Python 3.11+ with pip (python.org)
- Inno Setup 6 (jrsoftware.org/isinfo.php) — for the installer wrapper

**Steps:**
```
1. Open Command Prompt in the project folder
2. Double-click  build_windows.bat
3. Output: dist\installer\PGOps-Setup-1.0.0-Windows.exe
```

The installer:
- Installs to `Program Files` (or user folder without admin)
- Creates a Start Menu entry + optional Desktop shortcut
- Creates an optional startup entry
- Includes an uninstaller that safely stops PostgreSQL first

---

### macOS → `PGOps-x.x.x-macOS.dmg`

**Prerequisites:**
- Python 3.11+ (python.org)
- Homebrew (brew.sh) — for `create-dmg`

**Steps:**
```bash
chmod +x build_mac.sh
./build_mac.sh
# Output: dist/installer/PGOps-1.0.0-macOS.dmg
```

The DMG contains a drag-to-Applications installer window.

---

## How It Works

```
┌──────────────────────────────────────┐
│         HOST MACHINE                 │
│  ┌───────────────────────────────┐  │
│  │        PGOps              │  │
│  │  • Start / Stop postgres      │  │
│  │  • Show LAN IP + credentials  │  │
│  │  • Optional WiFi Hotspot      │  │
│  └──────────────┬────────────────┘  │
│                 │                    │
│         [PostgreSQL :5432]           │
└─────────────────┼────────────────────┘
                  │ LAN / Hotspot
       ┌──────────┴──────────┐
       │  Your other apps    │
       │  host: 192.168.x.x  │
       │  port: 5432         │
       └─────────────────────┘
```

---

## First Launch

1. Open PGOps
2. Click **"Download & Setup PostgreSQL"** — one-time download of portable binaries (~150 MB)
3. Click **"Start Server"**
4. Copy the connection details from the **Server** tab

---

## Connection Details

| Field    | Default        |
|----------|----------------|
| Host     | Your LAN IP    |
| Port     | 5432           |
| Username | postgres       |
| Password | postgres       |
| Database | mydb           |

Change any of these in the **Settings** tab.

---

## Connecting Your Apps

### Python
```python
import psycopg2
conn = psycopg2.connect(
    host="192.168.1.x", port=5432,
    user="postgres", password="postgres", dbname="mydb"
)
```

### Node.js
```js
const { Pool } = require('pg')
const pool = new Pool({
  host: '192.168.1.x', port: 5432,
  user: 'postgres', password: 'postgres', database: 'mydb'
})
```

### Laravel
```env
DB_CONNECTION=pgsql
DB_HOST=192.168.1.x
DB_PORT=5432
DB_DATABASE=mydb
DB_USERNAME=postgres
DB_PASSWORD=postgres
```

### Any connection string
```
postgresql://postgres:postgres@192.168.1.x:5432/mydb
```

---

## Firewall

**Windows** (run once as Administrator):
```cmd
netsh advfirewall firewall add rule name="PGOps" dir=in action=allow protocol=TCP localport=5432
```
(The Network tab has a copy button for this.)

**macOS:**
System Settings → Network → Firewall → Options → Add PGOps → Allow

---

## WiFi Hotspot Mode

If there's no router, PGOps can create its own WiFi network:

**Windows:**
1. Network tab → set SSID + password → Start Hotspot
2. Other devices join that WiFi
3. Use `192.168.137.1` as the host

**macOS:**
System Settings → General → Sharing → Internet Sharing
(macOS doesn't allow hotspot creation via command line in modern versions.)

---

## File Layout

```
pgops/
├── main.py                    # Entry point
├── pgops.spec             # PyInstaller build spec
├── requirements.txt
├── build_windows.bat          # Windows build + installer
├── build_mac.sh               # macOS build + DMG
├── src/
│   ├── core/
│   │   ├── pg_manager.py      # PostgreSQL process management
│   │   ├── config.py          # Settings persistence
│   │   └── hotspot.py         # WiFi hotspot control
│   └── ui/
│       └── main_window.py     # PyQt6 GUI
├── assets/
│   ├── icon.ico               # Windows icon (add yours)
│   └── icon.icns              # macOS icon (add yours)
└── installer/
    ├── windows.iss            # Inno Setup script
    └── mac/
        └── build_dmg.sh       # DMG creation script
```

---

## Adding Custom Icons

1. Create a 1024×1024 PNG of your icon
2. Convert to `.ico` (Windows): use https://convertio.co/png-ico/
3. Convert to `.icns` (Mac): `iconutil` or https://cloudconvert.com/png-to-icns
4. Place in `assets/`
5. Uncomment the `icon=` lines in `pgops.spec`

---

## Data Location

App data (config, pg binaries, database files) is stored next to the exe on Windows,
or next to the `.app` bundle on macOS. This keeps everything portable and self-contained.

To reset: stop the server, delete the `pgdata/` folder, and restart.
