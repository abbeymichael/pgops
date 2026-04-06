import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("PGOps")
    app.setApplicationDisplayName("PGOps")
    app.setQuitOnLastWindowClosed(False)

    # ── Auth gate ─────────────────────────────────────────────────────────────
    from core.auth import is_password_set
    from ui.login_dialog import LoginDialog, SetupPasswordDialog

    if not is_password_set():
        # First launch — prompt to create password
        setup = SetupPasswordDialog()
        if setup.exec() != SetupPasswordDialog.DialogCode.Accepted:
            sys.exit(0)
    else:
        # Every launch — show login screen
        login = LoginDialog()
        if login.exec() != LoginDialog.DialogCode.Accepted:
            sys.exit(0)

    # ── Launch main window ────────────────────────────────────────────────────
    from ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
