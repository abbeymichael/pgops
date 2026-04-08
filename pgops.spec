# pgops.spec  — Phase 2 edition
# Adds: caddy, frankenphp, dns_server, caddy_manager, frankenphp_manager,
#        app_manager, api_server, landing_server, tab_apps, tab_dns, pgops_cli

import sys
import os
import platform
from pathlib import Path

IS_MAC = platform.system() == "Darwin"
IS_WIN = platform.system() == "Windows"

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.', 'src'],
    binaries=[],
    datas=[
        ('src/core', 'core'),
        ('src/ui',   'ui'),
        ('assets',   'assets'),
    ],
    hiddenimports=[
        # ── Existing ──────────────────────────────────────────────────────────
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.sip',
        'requests',
        'core.db_manager',
        'core.scheduler',
        'core.mdns',
        'core.ssl_manager',
        'core.auth',
        'core.minio_manager',
        'core.pgadmin_manager',
        'core.bucket_manager',
        'ui.files_tab',
        'ui.login_dialog',
        'bcrypt',
        'ui.activity_monitor',
        'cryptography',
        'cryptography.x509',
        'cryptography.hazmat.primitives',
        'cryptography.hazmat.primitives.asymmetric',
        'core.network_info',
        'zeroconf',
        'zeroconf._utils',
        'zeroconf._dns',
        'core.service_manager',
        'ui.table_browser',
        'psycopg2',
        'psycopg2.extras',
        'qrcode',
        'PIL',
        'PIL.Image',
        # ── Phase 2 ───────────────────────────────────────────────────────────
        'dnslib',
        'dnslib.server',
        'dnslib.dns',
        'git',
        'git.repo',
        'git.remote',
        'core.dns_server',
        'core.caddy_manager',
        'core.frankenphp_manager',
        'core.app_manager',
        'core.api_server',
        'core.landing_server',
        'ui.tab_apps',
        'ui.tab_dns',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if IS_MAC:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name='PGOps',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )

    coll = COLLECT(
        exe, a.binaries, a.zipfiles, a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='PGOps',
    )

    app = BUNDLE(
        coll,
        name='PGOps.app',
        bundle_identifier='com.pgops.app',
        version='2.0.0',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'NSHighResolutionCapable': True,
            'LSUIElement': False,
            'NSAppleEventsUsageDescription': 'PGOps needs access to manage PostgreSQL.',
            'CFBundleShortVersionString': '2.0.0',
        },
    )

else:
    _ver = "version_info.txt" if os.path.exists("version_info.txt") else None
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name='PGOps',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        version=_ver,
        uac_admin=False,
    )

    coll = COLLECT(
        exe, a.binaries, a.zipfiles, a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='PGOps',
    )

# ── CLI binary ────────────────────────────────────────────────────────────────
# Build the pgops CLI as a separate one-file executable.
cli = Analysis(
    ['pgops_cli.py'],
    pathex=['.'],
    hiddenimports=[],
    excludes=['tkinter', 'PyQt6'],
)
cli_pyz = PYZ(cli.pure, cli.zipped_data, cipher=block_cipher)
cli_exe = EXE(
    cli_pyz, cli.scripts, cli.binaries, cli.zipfiles, cli.datas,
    name='pgops',
    debug=False,
    strip=False,
    upx=True,
    console=True,   # CLI must have a console
    onefile=True,
)
