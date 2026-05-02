"""
main_window.py  — Phase 2 edition (mDNS update)
Replaces DNSServerThread with MDNSServer for zero-config LAN discovery.
Domains changed from pgops.local / *.pgops.local  →  pgops.local / *.pgops.local
"""

import platform
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QStackedWidget,
    QMessageBox,
    QDialog,
    QFrame,
    QSystemTrayIcon,
    QMenu,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QIcon, QPixmap, QAction

from core.pg_manager import PostgresManager, BASE_DIR, DATA_DIR, LOG_FILE, _bin
from core.config import load_config, save_config
from core.pg_manager import get_app_data_dir
from core.mdns import MDNSBroadcaster, verify_mdns_resolution
from core.scheduler import BackupScheduler
from core.service_manager import service_exists
import core.db_manager as dbm
from core.minio_manager import MinIOManager
from core.pgadmin_manager import PgAdminManager

# Phase 2
from core.mdns_server import MDNSServer  # replaces DNSServerThread
from core.caddy_manager import CaddyManager, setup_caddy_binary
from core.frankenphp_manager import (
    AppProcessManager,
    setup_frankenphp_binary,
    is_frankenphp_available,
)
from core.app_manager import load_apps
from core.api_server import APIServer
from core.landing_server import LandingServer

from ui.tab_activity import ActivityTab
from ui.tab_server import ServerTab
from ui.tab_databases import DatabasesTab
from ui.tab_backup import BackupTab
from ui.tab_schedule import ScheduleTab
from ui.tab_settings import SettingsTab
from ui.tab_network import NetworkTab
from ui.tab_ssl import SslTab
from ui.tab_service import ServiceTab
from ui.tab_apps import AppsTab
from ui.tab_dns import DnsTab
from ui.files_tab import FilesTab
from ui.sidebar import Sidebar
from ui.header_bar import HeaderBar
from ui.login_dialog import ChangePasswordDialog as ChangePwDialog
from ui.theme import (
    APP_STYLE,
    C_SURFACE,
    C_SURFACE2,
    C_BORDER,
    C_BORDER2,
    C_TEXT,
    C_TEXT2,
    C_TEXT3,
    C_BLUE,
    C_GREEN,
    C_RED,
)


# ── Workers ───────────────────────────────────────────────────────────────────


class Worker(QThread):
    done = pyqtSignal(bool, str)
    progress = pyqtSignal(int)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            result = self.fn(self.progress.emit)
            if isinstance(result, tuple):
                ok = bool(result[0])
                msg = str(result[1]) if len(result) > 1 else ""
            elif result is None:
                ok, msg = True, ""
            else:
                ok, msg = bool(result), ""
            self.done.emit(ok, msg)
        except Exception as e:
            self.done.emit(False, str(e))


class _DbWorker(QThread):
    result = pyqtSignal(object, str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.result.emit(self.fn(), "")
        except Exception as e:
            self.result.emit(None, str(e))


# ── Main Window ───────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.manager = PostgresManager(self.config, log_callback=self._log)
        self._workers = []
        self._db_list = []

        self.scheduler = BackupScheduler(
            config_dir=get_app_data_dir(),
            backup_fn=self._scheduled_backup_fn,
            log_fn=self._log,
        )
        # Legacy mdns broadcaster (pgops.local via _postgresql._tcp)
        self.mdns = MDNSBroadcaster(port=self.config["port"], log_fn=self._log)
        self.minio = MinIOManager(self.config, log_fn=self._log)
        self.pgadmin = PgAdminManager(self.config, log_fn=self._log)

        # Phase 2 — mDNS server for .local LAN discovery
        self.mdns_server = MDNSServer(
            host_ip=self.manager.get_lan_ip(),
            log_fn=self._log,
        )
        self.caddy = CaddyManager(self.config, log_fn=self._log)
        self.app_procs = AppProcessManager(log_fn=self._log)
        self.landing_srv = LandingServer(
            get_apps=load_apps,
            get_host_ip=self.manager.get_lan_ip,
            log_fn=self._log,
        )
        self.api_server = APIServer(
            app_registry_fn=load_apps,
            process_manager=self.app_procs,
            postgres_manager=self.manager,
            minio_manager=self.minio,
            caddy_manager=self.caddy,
            admin_config=self.config,
            log_fn=self._log,
        )

        self.setWindowTitle("PGOps")
        self.setMinimumSize(1060, 700)
        self.resize(1240, 800)
        self.setStyleSheet(APP_STYLE)

        self._build_ui()
        self._build_tray()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(3000)

        QTimer.singleShot(1500, self._initial_load)

        if self.config.get("autostart"):
            QTimer.singleShot(800, self._start)
        if self.scheduler.schedule.get("enabled"):
            self.scheduler.start()

        # Staggered Phase 2 startup
        QTimer.singleShot(500, self._auto_start_mdns)
        QTimer.singleShot(600, self._start_mdns_server)  # mDNS .local broadcast
        QTimer.singleShot(700, self._start_landing_server)
        QTimer.singleShot(800, self._start_api_server)
        QTimer.singleShot(2000, self._start_caddy_and_apps)

    # ── Phase 2 startup helpers ───────────────────────────────────────────────

    def _start_mdns_server(self):
        """Start the MDNSServer and register all PGOps service subdomains."""
        ok, msg = self.mdns_server.start()
        self._log(msg)

        # Register the fixed infrastructure subdomains so LAN devices can
        # resolve minio.pgops.local, console.pgops.local, pgadmin.pgops.local
        # in addition to app-specific subdomains.
        for hostname in ("minio.pgops", "console.pgops", "pgadmin.pgops"):
            self.mdns_server.register_app("", domain=f"{hostname}.local")

        # Register any already-deployed apps
        for app in load_apps():
            domain = app.get("domain", "")
            if domain:
                self.mdns_server.register_app(app["id"], domain)

        if hasattr(self, "_dns_tab"):
            self._dns_tab.refresh()

    def _start_landing_server(self):
        ok, msg = self.landing_srv.start()
        self._log(msg)

    def _start_api_server(self):
        ok, msg = self.api_server.start()
        self._log(msg)

    def _start_caddy_and_apps(self):
        apps = load_apps()
        running_apps = [a for a in apps if a.get("status") == "running"]
        if running_apps:
            results = self.app_procs.start_all(running_apps)
            for app_id, ok, msg in results:
                self._log(f"[App:{app_id}] {msg}")
        if self.caddy.is_available():
            # pgadmin_running flag kept for compat but no longer controls the
            # pgadmin block — it is always written in generate_caddyfile()
            ok, msg = self.caddy.start(apps, pgadmin_running=self.pgadmin.is_running())
            self._log(msg)
        else:
            self._log("[Caddy] Binary not found — click Setup Caddy in the Server tab.")

    def _initial_load(self):
        self._poll()
        if self.manager.is_running():
            self._load_databases_async()

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        self._sidebar = Sidebar()
        self._sidebar.nav_changed.connect(self._on_nav)
        h.addWidget(self._sidebar)

        right = QWidget()
        right.setStyleSheet("background:#1a1d23;")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        self._hbar = HeaderBar()
        rv.addWidget(self._hbar)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background:#1a1d23;")
        rv.addWidget(self._stack)

        h.addWidget(right, 1)
        self._page_idx: dict[str, int] = {}
        self._build_pages()

    def _add_page(self, key, widget):
        self._page_idx[key] = self._stack.addWidget(widget)

    def _build_pages(self):
        self._srv_tab = ServerTab(
            manager=self.manager,
            config=self.config,
            minio=self.minio,
            pgadmin=self.pgadmin,
            on_start=self._start,
            on_stop=self._stop,
            on_download=self._download,
            on_start_pgadmin=self._start_pgadmin,
            on_stop_pgadmin=self._stop_pgadmin,
            on_open_pgadmin=self._open_pgadmin,
            on_reset_pgadmin=self._reset_pgadmin,
            on_setup_caddy=self._setup_caddy,
            on_start_caddy=self._start_caddy,
            on_stop_caddy=self._stop_caddy,
            on_setup_frankenphp=self._setup_frankenphp,
            on_start_frankenphp=self._start_all_apps,
            on_stop_frankenphp=self._stop_all_apps,
            caddy_manager=self.caddy,
            frankenphp_manager=self.app_procs,
            log_fn=self._log,
        )
        self._add_page("server", self._srv_tab)

        self.activity = ActivityTab(self.config)
        self._add_page("activity", self.activity)

        self._db_tab = DatabasesTab(
            config=self.config,
            manager=self.manager,
            on_create=self._create_database,
            on_drop=self._drop_database,
            on_change_pw=self._change_password,
            on_refresh=self._load_databases_async,
        )
        self._add_page("databases", self._db_tab)

        self._apps_tab = AppsTab(
            config=self.config,
            process_manager=self.app_procs,
            caddy_manager=self.caddy,
        )
        self._add_page("apps", self._apps_tab)

        self.files_tab = FilesTab(self.minio)
        self._add_page("files", self.files_tab)

        self._backup_tab = BackupTab(
            config=self.config,
            on_backup=None,
            on_restore=None,
            on_refresh_dbs=self._load_databases_async,
            on_log=self._log,
        )
        self._add_page("backup", self._backup_tab)

        self._sched_tab = ScheduleTab(
            scheduler=self.scheduler,
            on_save=self._save_schedule,
            on_log=self._log,
        )
        self._add_page("schedule", self._sched_tab)

        self._ssl_tab = SslTab(
            config=self.config,
            manager=self.manager,
            on_log=self._log,
            caddy_manager=self.caddy,
        )
        self._add_page("ssl", self._ssl_tab)

        self._svc_tab = ServiceTab(
            config=self.config, manager=self.manager, on_log=self._log
        )
        self._add_page("service", self._svc_tab)

        self._settings_tab = SettingsTab(
            config=self.config,
            on_save=self._save_settings,
            on_change_pw=self._change_app_password,
            on_log=self._log,
        )
        self._add_page("settings", self._settings_tab)

        self._net_tab = NetworkTab(
            config=self.config,
            mdns=self.mdns,
            manager=self.manager,
            on_mdns_start=self._start_mdns,
            on_mdns_stop=self._stop_mdns,
            on_mdns_test=self._test_mdns,
            on_pin=self._pin_ip,
            on_unpin=self._unpin_ip,
            on_log=self._log,
        )
        self._add_page("network", self._net_tab)

        # DNS tab now shows mDNS controls
        self._dns_tab = DnsTab(
            mdns_server=self.mdns_server,
            get_host_ip=self.manager.get_lan_ip,
            on_log=self._log,
        )
        self._add_page("dns", self._dns_tab)

        self._add_page("log", self._tab_log())

    def _tab_log(self):
        w = QWidget()
        w.setStyleSheet("background:#1a1d23;")
        v = QVBoxLayout(w)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(10)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet(
            f"background:{C_SURFACE};color:{C_GREEN};"
            f"font-family:'Consolas','Courier New',monospace;"
            f"font-size:12px;border:1px solid {C_BORDER};border-radius:8px;padding:10px;"
        )
        clr = QPushButton("Clear Log")
        clr.setFixedHeight(30)
        clr.setCursor(Qt.CursorShape.PointingHandCursor)
        clr.setStyleSheet(
            f"QPushButton{{background:{C_SURFACE2};color:{C_TEXT2};"
            f"border:1px solid {C_BORDER2};border-radius:6px;"
            f"font-size:12px;font-weight:600;padding:0 16px;}}"
            f"QPushButton:hover{{background:{C_BORDER2};color:{C_TEXT};}}"
        )
        clr.clicked.connect(self.log_box.clear)
        v.addWidget(self.log_box)
        v.addWidget(clr)
        return w

    # ── Navigation ────────────────────────────────────────────────────────────

    def _on_nav(self, key):
        self._stack.setCurrentIndex(self._page_idx.get(key, 0))
        TITLES = {
            "server": ("THE COMMAND CONSOLE", "PGOps Orchestrator"),
            "activity": ("THE COMMAND CONSOLE", "Activity Monitor"),
            "databases": ("THE COMMAND CONSOLE", "Databases"),
            "apps": ("THE COMMAND CONSOLE", "Web Applications"),
            "files": ("THE COMMAND CONSOLE", "Storage"),
            "backup": ("THE COMMAND CONSOLE", "Backup & Restore"),
            "schedule": ("THE COMMAND CONSOLE", "Schedule"),
            "ssl": ("THE COMMAND CONSOLE", "SSL / TLS"),
            "service": ("THE COMMAND CONSOLE", "Service"),
            "settings": ("THE COMMAND CONSOLE", "Settings"),
            "network": ("THE COMMAND CONSOLE", "Network"),
            "dns": ("THE COMMAND CONSOLE", "Network Discovery"),
            "log": ("THE COMMAND CONSOLE", "Log"),
        }
        sec, pg = TITLES.get(key, ("THE COMMAND CONSOLE", ""))
        self._hbar.set_title(sec, pg)
        if key == "activity":
            if self.manager.is_running():
                self.activity.start_monitoring()
        else:
            self.activity.stop_monitoring()
        if key == "service":
            self._svc_tab.update_status()
        if key == "ssl":
            self._ssl_tab.refresh_status()
        if key == "dns":
            self._dns_tab.refresh()
        if key == "apps":
            self._apps_tab.refresh()

    # ── Tray ──────────────────────────────────────────────────────────────────

    def _build_tray(self):
        px = QPixmap(16, 16)
        px.fill(QColor(C_BLUE))
        self.tray = QSystemTrayIcon(QIcon(px), self)
        m = QMenu()
        m.addAction(QAction("Show", self, triggered=self.show))
        m.addSeparator()
        m.addAction(QAction("Start Server", self, triggered=self._start))
        m.addAction(QAction("Stop Server", self, triggered=self._stop))
        m.addSeparator()
        m.addAction(QAction("Quit", self, triggered=self._quit))
        self.tray.setContextMenu(m)
        self.tray.activated.connect(
            lambda r: (
                self.show()
                if r == QSystemTrayIcon.ActivationReason.DoubleClick
                else None
            )
        )
        self.tray.show()

    def closeEvent(self, e):
        e.ignore()
        self.hide()
        self.tray.showMessage(
            "PGOps",
            "Running in system tray.",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )

    def _quit(self):
        self.scheduler.stop()
        self.mdns.stop()
        self.mdns_server.stop()  # stop mDNS .local broadcast
        self.app_procs.stop_all()
        self.caddy.stop()
        self.api_server.stop()
        self.landing_srv.stop()
        if self.minio.is_running():
            self.minio.stop()
        if self.pgadmin.is_running():
            self.pgadmin.stop()
        if self.manager.is_running() and not service_exists():
            self.manager.stop()
        QApplication.quit()

    # ── PostgreSQL ────────────────────────────────────────────────────────────

    def _start(self):
        if not self.manager.is_binaries_available():
            self._srv_tab.show_warn(True)
            return
        self._srv_tab.btn_start.setEnabled(False)

        def fn(_p):
            return self.manager.start(), ""

        self._run(fn, self._on_start_done)

    def _on_start_done(self, ok, msg):
        self._srv_tab.btn_start.setEnabled(True)
        self._poll()
        if ok:
            self._load_databases_async()
            self._backup_tab.refresh_backup_list()
            self._ssl_tab.refresh_status()
            if not self.minio.is_running() and self.minio.is_binaries_available():

                def _sm(_p):
                    return self.minio.start()

                self._run(_sm, lambda ok, msg: self._log(f"[MinIO] {msg}"))
            if not self.pgadmin.is_running() and self.pgadmin.is_available():

                def _spa(_p):
                    # Pass the Caddy HTTPS port so pgAdmin's config_local.py
                    # gets the correct public URL for CSRF validation
                    return self.pgadmin.start(caddy_https_port=self.caddy.https_port)

                self._run(
                    _spa,
                    lambda ok, msg: (
                        self._log(f"[pgAdmin] {msg}"),
                        self._update_pgadmin_status(),
                        # Reload Caddy so pgadmin subdomain is live
                        (
                            self.caddy.update_apps(load_apps())
                            if self.caddy.is_running()
                            else None
                        ),
                    ),
                )
            if not self.caddy.is_running():
                QTimer.singleShot(500, self._start_caddy_and_apps)

    def _stop(self):
        self._srv_tab.btn_stop.setEnabled(False)
        if self.minio.is_running():
            self.minio.stop()
        if self.pgadmin.is_running():
            self.pgadmin.stop()

        def fn(_p):
            return self.manager.stop(), ""

        self._run(
            fn, lambda ok, msg: (self._srv_tab.btn_stop.setEnabled(True), self._poll())
        )

    def _download(self):
        self._srv_tab.btn_setup.setEnabled(False)
        self._srv_tab.set_progress(True, 0)

        def fn(pc):
            self.manager.setup_binaries(progress_callback=pc)
            return True, ""

        w = self._run(fn, self._on_dl_done)
        w.progress.connect(lambda v: self._srv_tab.set_progress(True, v))

    def _on_dl_done(self, ok, msg):
        self._srv_tab.set_progress(False)
        self._srv_tab.btn_setup.setEnabled(True)
        if ok:
            self._srv_tab.show_warn(False)
            self._log("Setup complete. Click Start Server.")
        else:
            self._log(f"Setup failed: {msg}")

    # ── Caddy ────────────────────────────────────────────────────────────────

    def _setup_caddy(self):
        self._srv_tab.btn_caddy_setup.setEnabled(False)
        self._srv_tab.set_caddy_progress(True, 0)

        def fn(pc):
            return setup_caddy_binary(progress_callback=pc)

        def done(ok, msg):
            self._srv_tab.set_caddy_progress(False)
            self._srv_tab.btn_caddy_setup.setEnabled(True)
            self._log(f"[Caddy] {msg}")
            self._poll()

        w = self._run(fn, done)
        w.progress.connect(lambda v: self._srv_tab.set_caddy_progress(True, v))

    def _start_caddy(self):
        if not self.caddy.is_available():
            QMessageBox.information(
                self, "Setup Required",
                "Click Setup Caddy first to download the binary.",
            )
            return
        self._srv_tab.btn_caddy_start.setEnabled(False)
 
        def fn(_p):
            apps = load_apps()
            return self.caddy.start(apps, pgadmin_running=self.pgadmin.is_running())
 
        def done(ok, msg):
            self._srv_tab.btn_caddy_start.setEnabled(True)
            self._log(f"[Caddy] {msg}")
            self._poll()
 
        self._run(fn, done)
 

    def _stop_caddy(self):
        self._srv_tab.btn_caddy_stop.setEnabled(False)

        def fn(_p):
            return self.caddy.stop()

        def done(ok, msg):
            self._srv_tab.btn_caddy_stop.setEnabled(True)
            self._log(f"[Caddy] {msg}")
            self._poll()

        self._run(fn, done)

    # ── FrankenPHP ────────────────────────────────────────────────────────────

    def _setup_frankenphp(self):
        self._srv_tab.btn_fphp_setup.setEnabled(False)
        self._srv_tab.set_fphp_progress(True, 0)

        def fn(pc):
            return setup_frankenphp_binary(progress_callback=pc)

        def done(ok, msg):
            self._srv_tab.set_fphp_progress(False)
            self._srv_tab.btn_fphp_setup.setEnabled(True)
            self._log(f"[FrankenPHP] {msg}")
            self._poll()

        w = self._run(fn, done)
        w.progress.connect(lambda v: self._srv_tab.set_fphp_progress(True, v))

    def _start_all_apps(self):
        if not is_frankenphp_available():
            QMessageBox.information(
                self,
                "Setup Required",
                "Click Setup FrankenPHP first to download the binary.",
            )
            return
        apps = [a for a in load_apps() if a.get("status") == "running"]
        if not apps:
            self._log("[FrankenPHP] No apps marked as running in apps.json.")
            return
        self._srv_tab.btn_fphp_start.setEnabled(False)

        def fn(_p):
            results = self.app_procs.start_all(apps)
            return True, f"Started {len(results)} app(s)."

        def done(ok, msg):
            self._srv_tab.btn_fphp_start.setEnabled(True)
            self._log(f"[FrankenPHP] {msg}")
            self._poll()

        self._run(fn, done)

    def _stop_all_apps(self):
        self._srv_tab.btn_fphp_stop.setEnabled(False)

        def fn(_p):
            self.app_procs.stop_all()
            return True, "All app processes stopped."

        def done(ok, msg):
            self._srv_tab.btn_fphp_stop.setEnabled(True)
            self._log(f"[FrankenPHP] {msg}")
            self._poll()

        self._run(fn, done)

    # ── Database operations ───────────────────────────────────────────────────

    def _load_databases_async(self):
        if not self.manager.is_running():
            return
        cfg = self.config

        def fn():
            return dbm.list_databases(cfg["username"], cfg["password"], cfg["port"])

        def done(dbs, error):
            if error:
                self._log(f"DB list error: {error}")
                return
            if dbs is None:
                return
            self._db_list = dbs
            self._db_tab.populate(dbs, self.manager)
            self._backup_tab.populate_dbs([db["name"] for db in dbs])
            self._sched_tab.populate_dbs([db["name"] for db in dbs])

        w = _DbWorker(fn)
        w.result.connect(done)
        w.start()
        self._workers.append(w)

    def _create_database(self):
        if not self.manager.is_running():
            QMessageBox.warning(self, "Server Not Running", "Start the server first.")
            return
        from ui.tab_databases import CreateDbDialog

        dlg = CreateDbDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        dbname, owner, password = dlg.values()

        def fn(_p):
            return dbm.create_database(
                dbname,
                owner,
                password,
                self.config["username"],
                self.config["password"],
                self.config["port"],
            )

        def done(ok, msg):
            self._log(msg)
            if ok:
                self._load_databases_async()
            else:
                QMessageBox.critical(self, "Error", msg)

        self._run(fn, done)

    def _drop_database(self, dbname):
        if (
            QMessageBox.question(
                self,
                "Drop Database",
                f"Permanently delete '{dbname}'?\n\nThis cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        def fn(_p):
            return dbm.drop_database(
                dbname,
                self.config["username"],
                self.config["password"],
                self.config["port"],
            )

        self._run(fn, lambda ok, msg: (self._log(msg), self._load_databases_async()))

    def _change_password(self, dbname):
        from ui.tab_databases import ChangePwDialog as DbChPw

        owner = next(
            (db["owner"] for db in self._db_list if db["name"] == dbname), dbname
        )
        dlg = DbChPw(owner, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_pw = dlg.value()

        def fn(_p):
            return dbm.change_role_password(
                owner,
                new_pw,
                self.config["username"],
                self.config["password"],
                self.config["port"],
            )

        self._run(fn, lambda ok, msg: self._log(msg))

    # ── Schedule ──────────────────────────────────────────────────────────────

    def _save_schedule(self, schedule_dict):
        self.scheduler.update(**schedule_dict)
        self._sched_tab.refresh_next_run()
        self._log(
            f"Schedule saved. {'Running.' if schedule_dict['enabled'] else 'Disabled.'}"
        )

    def _scheduled_backup_fn(self, dbname):
        return dbm.backup_database(
            dbname,
            self.config["username"],
            self.config["password"],
            self.config["port"],
        )

    # ── Settings ──────────────────────────────────────────────────────────────

    def _save_settings(self, new_cfg):
        self.config.update(new_cfg)
        save_config(self.config)
        self.manager.config = self.config
        self.minio.config = self.config
        self.pgadmin.pg_config = self.config
        self.caddy.config = self.config
        self.api_server._cfg = self.config
        self.activity.update_config(self.config)
        self._db_tab.update_config(self.config)
        self._backup_tab.update_config(self.config)
        self._net_tab.update_config(self.config)
        self._ssl_tab.config = self.config

    def _change_app_password(self):
        dlg = ChangePwDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(
                self, "Password Changed", "Master password updated."
            )
            self._log("App password changed.")

    # ── pgAdmin ───────────────────────────────────────────────────────────────

    def _start_pgadmin(self):
        if not self.pgadmin.is_available():
            QMessageBox.warning(
                self,
                "Not Available",
                "pgAdmin 4 not found. Run Setup PostgreSQL first.",
            )
            return
        self._srv_tab.btn_pga_start.setEnabled(False)

        caddy_port = self.caddy.https_port

        def fn(_p):
            return self.pgadmin.start(caddy_https_port=caddy_port)

        def done(ok, msg):
            self._srv_tab.btn_pga_start.setEnabled(True)
            self._log(f"[pgAdmin] {msg}")
            self._update_pgadmin_status()
            if ok:
                # Reload Caddy so the pgadmin.pgops.local block is active
                if self.caddy.is_running():
                    self.caddy.update_apps(load_apps())
                # Open the browser at the HTTPS subdomain, not the raw port
                import webbrowser

                webbrowser.open(self.pgadmin.public_url(caddy_port))

        self._run(fn, done)

    def _stop_pgadmin(self):
        def fn(_p):
            return self.pgadmin.stop()

        self._run(
            fn,
            lambda ok, msg: (
                self._log(f"[pgAdmin] {msg}"),
                self._update_pgadmin_status(),
            ),
        )

    def _open_pgadmin(self):
        if not self.pgadmin.is_running():
            QMessageBox.information(self, "pgAdmin Not Running", "Start pgAdmin first.")
            return
        import webbrowser

        # Always open through Caddy's HTTPS subdomain, never the raw port
        webbrowser.open(self.pgadmin.public_url(self.caddy.https_port))

    def _reset_pgadmin(self):
        reply = QMessageBox.question(
            self,
            "Reset pgAdmin",
            "Stop pgAdmin, delete its database, and restart fresh?\n\n"
            "Log in after reset with:\n"
            f"  Email:    {self.pgadmin.default_credentials()['email']}\n"
            f"  Password: {self.pgadmin.default_credentials()['password']}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._srv_tab.btn_pga_reset.setEnabled(False)
        self._srv_tab.btn_pga_start.setEnabled(False)

        caddy_port = self.caddy.https_port

        def fn(_p):
            return self.pgadmin.reset_and_restart(caddy_https_port=caddy_port)

        def done(ok, msg):
            self._srv_tab.btn_pga_reset.setEnabled(True)
            self._srv_tab.btn_pga_start.setEnabled(True)
            self._log(f"[pgAdmin] {msg}")
            self._update_pgadmin_status()
            if ok:
                if self.caddy.is_running():
                    self.caddy.update_apps(load_apps())
                import webbrowser

                webbrowser.open(self.pgadmin.public_url(caddy_port))

        self._run(fn, done)

    def _update_pgadmin_status(self):
        self._srv_tab.update_pgadmin_status(
            self.pgadmin.is_running(), self.pgadmin.is_available()
        )

    # ── Legacy mDNS (postgresql service broadcaster) ──────────────────────────

    def _auto_start_mdns(self):
        ok, msg = self.mdns.start()
        self._log(msg)
        self._update_mdns_status()

    def _start_mdns(self):
        ok, msg = self.mdns.start()
        self._log(msg)
        self._update_mdns_status()

    def _stop_mdns(self):
        reply = QMessageBox.question(
            self,
            "Stop Broadcasting",
            "pgops.local is the hostname all apps use.\n"
            "Stopping it will make pgops.local unreachable.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        ok, msg = self.mdns.stop()
        self._log(msg)
        self._update_mdns_status()

    def _test_mdns(self):
        ok, msg = verify_mdns_resolution()
        self._log(f"[mDNS Test] {msg}")
        self._net_tab.update_mdns_status(ok, self.manager.get_lan_ip() if ok else "")

    def _update_mdns_status(self):
        if hasattr(self, "_net_tab"):
            ip = self.manager.get_lan_ip() if self.mdns.is_running() else ""
            self._net_tab.update_mdns_status(self.mdns.is_running(), ip)

    # ── IP pinning ────────────────────────────────────────────────────────────

    def _pin_ip(self, ip):
        self.config["preferred_ip"] = ip
        save_config(self.config)
        self.manager.config = self.config
        # Update mDNS server with the pinned IP
        self.mdns_server.update_ip(ip)
        self._log(f"Pinned host IP: {ip}")
        self._poll()

    def _unpin_ip(self):
        self.config["preferred_ip"] = ""
        save_config(self.config)
        self.manager.config = self.config
        self._log("IP pin removed — auto-detect enabled.")
        self._poll()

    # ── Poll (3 s timer) ──────────────────────────────────────────────────────

    def _poll(self):
        running = self.manager.is_running()
        cfg = {**self.config}
        if running:
            d = self.manager.connection_details()
            cfg["_host"] = self.manager.get_lan_ip()
            cfg.update(d)

        self._srv_tab.update_server_status(
            running, cfg, self.manager.connection_string() if running else ""
        )
        if not self.manager.is_binaries_available():
            self._srv_tab.show_warn(True)

        self._update_pgadmin_status()

        self._srv_tab.update_caddy_status(
            running=self.caddy.is_running(),
            available=self.caddy.is_available(),
        )

        live_count = sum(
            1 for app_id, proc in self.app_procs.processes.items() if proc.is_running
        )
        self._srv_tab.update_frankenphp_status(
            running_count=live_count,
            available=is_frankenphp_available(),
        )

        if hasattr(self, "_svc_tab"):
            self._svc_tab.update_status()
        if hasattr(self, "_sched_tab"):
            self._sched_tab.refresh_next_run()

        self._update_mdns_status()

        # Keep mDNS server IP in sync with LAN IP changes
        current_ip = self.manager.get_lan_ip()
        if self.mdns_server.host_ip != current_ip:
            self.mdns_server.update_ip(current_ip)

        # Keep mDNS app registrations in sync
        if self.mdns_server.is_running():
            self.mdns_server.sync_apps(load_apps())

        # Refresh DNS tab periodically
        if hasattr(self, "_dns_tab"):
            self._dns_tab.refresh()

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(self, msg):
        if hasattr(self, "log_box"):
            self.log_box.append(str(msg))
            self.log_box.verticalScrollBar().setValue(
                self.log_box.verticalScrollBar().maximum()
            )
        if hasattr(self, "_srv_tab"):
            self._srv_tab.append_log(str(msg))

    # ── Worker helper ─────────────────────────────────────────────────────────

    def _run(self, fn, on_done) -> Worker:
        w = Worker(fn)
        w.done.connect(on_done)
        w.start()
        self._workers.append(w)
        self._workers = [x for x in self._workers if x.isRunning()]
        return w
