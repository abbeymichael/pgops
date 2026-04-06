# pgops.spec
# Used by PyInstaller to build the app.
# Run: pyinstaller pgops.spec

import sys
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
        # icon='assets/icon.icns',   # Uncomment once you have an icon
        bundle_identifier='com.pgops.app',
        version='1.0.0',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'NSHighResolutionCapable': True,
            'LSUIElement': False,
            'NSAppleEventsUsageDescription': 'PGOps needs access to manage PostgreSQL.',
            'CFBundleShortVersionString': '1.0.0',
        },
    )

else:
    import os
    _ver = "version_info.txt" if os.path.exists("version_info.txt") else None
    # Windows — single-folder build (onedir, not onefile, so pg binaries can sit next to exe)
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name='PGOps',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        # icon='assets/icon.ico',   # Uncomment once you have an icon
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
