"""
login_dialog.py
Login screen shown on every launch.
Setup screen shown on first launch to create the master password.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QWidget,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeyEvent

from core.auth import verify_password, set_password, reset_password, is_password_set


DIALOG_STYLE = """
QDialog {
    background: #0a0f1e;
}
QWidget {
    background: #0a0f1e;
    color: #e2e8f0;
}
QLineEdit {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 10px 14px;
    color: #e2e8f0;
    font-size: 14px;
}
QLineEdit:focus {
    border: 1px solid #3b82f6;
}
"""


def _btn(text, bg="#1d4ed8", hover="#1e40af", fg="white", h=42):
    b = QPushButton(text)
    b.setFixedHeight(h)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:none;"
        f"border-radius:6px;font-size:13px;font-weight:600;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:disabled{{background:#1e293b;color:#475569;}}"
    )
    return b


# ─── Login Dialog ─────────────────────────────────────────────────────────────
class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PGOps")
        self.setFixedSize(380, 340)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.CustomizeWindowHint
        )
        self.setStyleSheet(DIALOG_STYLE)
        self._attempts = 0
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 36, 40, 36)
        layout.setSpacing(0)

        # Logo / title
        logo = QLabel("PG")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            "color:#3b82f6;font-size:36px;font-weight:900;"
            "letter-spacing:2px;background:transparent;"
        )
        title = QLabel("PGOps")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "color:#fff;font-size:22px;font-weight:700;background:transparent;"
        )
        sub = QLabel("Enter your password to continue")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color:#475569;font-size:12px;background:transparent;")

        layout.addWidget(logo)
        layout.addWidget(title)
        layout.addSpacing(4)
        layout.addWidget(sub)
        layout.addSpacing(28)

        # Password field
        self.pw_field = QLineEdit()
        self.pw_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_field.setPlaceholderText("Password")
        self.pw_field.returnPressed.connect(self._login)
        layout.addWidget(self.pw_field)
        layout.addSpacing(12)

        # Error label
        self.error_lbl = QLabel("")
        self.error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_lbl.setStyleSheet(
            "color:#ef4444;font-size:12px;background:transparent;"
        )
        self.error_lbl.setVisible(False)
        layout.addWidget(self.error_lbl)
        layout.addSpacing(8)

        # Unlock button
        self.btn_login = _btn("Unlock PGOps")
        self.btn_login.clicked.connect(self._login)
        layout.addWidget(self.btn_login)
        layout.addSpacing(16)

        # Forgot password link
        forgot = QPushButton("Forgot password?")
        forgot.setStyleSheet(
            "QPushButton{background:transparent;color:#475569;"
            "border:none;font-size:11px;text-decoration:underline;}"
            "QPushButton:hover{color:#94a3b8;}"
        )
        forgot.clicked.connect(self._forgot)
        layout.addWidget(forgot, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()
        self.pw_field.setFocus()

    def _login(self):
        pw = self.pw_field.text()
        if not pw:
            self._show_error("Please enter your password.")
            return

        if verify_password(pw):
            self.accept()
        else:
            self._attempts += 1
            self.pw_field.clear()
            self.pw_field.setFocus()

            if self._attempts >= 5:
                self._show_error(
                    f"Incorrect password ({self._attempts} attempts). "
                    "Use 'Forgot password?' to reset."
                )
            else:
                remaining = 5 - self._attempts
                self._show_error(
                    f"Incorrect password. {remaining} attempt{'s' if remaining != 1 else ''} remaining."
                )
            # Shake animation
            self._shake()

    def _show_error(self, msg: str):
        self.error_lbl.setText(msg)
        self.error_lbl.setVisible(True)

    def _shake(self):
        orig = self.x()
        for i, offset in enumerate([6, -6, 4, -4, 2, -2, 0]):
            QTimer.singleShot(i * 40, lambda x=orig + offset: self.move(x, self.y()))

    def _forgot(self):
        QMessageBox.information(
            self,
            "Reset Password",
            "To reset your password:\n\n"
            "1. Close this dialog\n"
            "2. Delete the file:\n\n"
            "   %LOCALAPPDATA%\\PGOps\\auth.json\n\n"
            "   (Windows) or\n\n"
            "   ~/Library/Application Support/PGOps/auth.json\n\n"
            "   (macOS)\n\n"
            "3. Relaunch PGOps — you will be prompted to set a new password.\n\n"
            "Note: Your databases and data are not affected."
        )


# ─── First-Time Setup Dialog ──────────────────────────────────────────────────
class SetupPasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PGOps — Setup")
        self.setFixedSize(400, 420)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.CustomizeWindowHint
        )
        self.setStyleSheet(DIALOG_STYLE)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 36, 40, 36)
        layout.setSpacing(0)

        logo = QLabel("PG")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            "color:#3b82f6;font-size:36px;font-weight:900;"
            "background:transparent;"
        )
        title = QLabel("Welcome to PGOps")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "color:#fff;font-size:20px;font-weight:700;background:transparent;"
        )
        sub = QLabel("Set a master password to protect this app.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#475569;font-size:12px;background:transparent;")

        layout.addWidget(logo)
        layout.addWidget(title)
        layout.addSpacing(6)
        layout.addWidget(sub)
        layout.addSpacing(28)

        # Password fields
        self.pw1 = QLineEdit()
        self.pw1.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw1.setPlaceholderText("Choose a password (min 4 characters)")
        layout.addWidget(self.pw1)
        layout.addSpacing(10)

        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw2.setPlaceholderText("Confirm password")
        self.pw2.returnPressed.connect(self._save)
        layout.addWidget(self.pw2)
        layout.addSpacing(10)

        # Strength indicator
        self.strength_lbl = QLabel("")
        self.strength_lbl.setStyleSheet("color:#64748b;font-size:11px;background:transparent;")
        layout.addWidget(self.strength_lbl)
        self.pw1.textChanged.connect(self._check_strength)
        layout.addSpacing(6)

        # Error label
        self.error_lbl = QLabel("")
        self.error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_lbl.setStyleSheet(
            "color:#ef4444;font-size:12px;background:transparent;"
        )
        self.error_lbl.setVisible(False)
        layout.addWidget(self.error_lbl)
        layout.addSpacing(10)

        btn_save = _btn("Set Password & Continue")
        btn_save.clicked.connect(self._save)
        layout.addWidget(btn_save)
        layout.addSpacing(14)

        note = QLabel(
            "This password protects access to PGOps.\n"
            "It does not affect your database credentials."
        )
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setWordWrap(True)
        note.setStyleSheet("color:#334155;font-size:11px;background:transparent;")
        layout.addWidget(note)
        layout.addStretch()

        self.pw1.setFocus()

    def _check_strength(self, pw: str):
        if not pw:
            self.strength_lbl.setText("")
            return
        score = 0
        if len(pw) >= 8:  score += 1
        if len(pw) >= 12: score += 1
        if any(c.isupper() for c in pw): score += 1
        if any(c.isdigit() for c in pw): score += 1
        if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in pw): score += 1

        labels = [
            (1, "Weak",   "#ef4444"),
            (2, "Fair",   "#f59e0b"),
            (3, "Good",   "#3b82f6"),
            (5, "Strong", "#22c55e"),
        ]
        for threshold, label, color in labels:
            if score <= threshold:
                self.strength_lbl.setText(f"Strength: {label}")
                self.strength_lbl.setStyleSheet(
                    f"color:{color};font-size:11px;background:transparent;"
                )
                return
        self.strength_lbl.setText("Strength: Strong")
        self.strength_lbl.setStyleSheet(
            "color:#22c55e;font-size:11px;background:transparent;"
        )

    def _save(self):
        pw1 = self.pw1.text()
        pw2 = self.pw2.text()

        if not pw1:
            self._err("Please choose a password.")
            return
        if len(pw1) < 4:
            self._err("Password must be at least 4 characters.")
            return
        if pw1 != pw2:
            self._err("Passwords do not match.")
            self.pw2.clear()
            self.pw2.setFocus()
            return

        ok, msg = set_password(pw1)
        if ok:
            self.accept()
        else:
            self._err(msg)

    def _err(self, msg: str):
        self.error_lbl.setText(msg)
        self.error_lbl.setVisible(True)


# ─── Change Password Dialog ───────────────────────────────────────────────────
class ChangePasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change Password")
        self.setFixedSize(380, 360)
        self.setStyleSheet(DIALOG_STYLE)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.setSpacing(10)

        title = QLabel("Change Master Password")
        title.setStyleSheet(
            "color:#e2e8f0;font-size:16px;font-weight:700;background:transparent;"
        )
        layout.addWidget(title)
        layout.addSpacing(8)

        for attr, placeholder in [
            ("current_pw", "Current password"),
            ("new_pw1",    "New password (min 4 characters)"),
            ("new_pw2",    "Confirm new password"),
        ]:
            f = QLineEdit()
            f.setEchoMode(QLineEdit.EchoMode.Password)
            f.setPlaceholderText(placeholder)
            setattr(self, attr, f)
            layout.addWidget(f)

        self.new_pw2.returnPressed.connect(self._save)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet(
            "color:#ef4444;font-size:12px;background:transparent;"
        )
        self.error_lbl.setVisible(False)
        layout.addWidget(self.error_lbl)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_cancel = _btn("Cancel", "#1e293b", "#334155", "#94a3b8", h=38)
        btn_save   = _btn("Change Password", h=38)
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

        self.current_pw.setFocus()

    def _save(self):
        cur  = self.current_pw.text()
        new1 = self.new_pw1.text()
        new2 = self.new_pw2.text()

        if not verify_password(cur):
            self._err("Current password is incorrect.")
            self.current_pw.clear()
            self.current_pw.setFocus()
            return
        if len(new1) < 4:
            self._err("New password must be at least 4 characters.")
            return
        if new1 != new2:
            self._err("New passwords do not match.")
            self.new_pw2.clear()
            self.new_pw2.setFocus()
            return

        ok, msg = set_password(new1)
        if ok:
            self.accept()
        else:
            self._err(msg)

    def _err(self, msg: str):
        self.error_lbl.setText(msg)
        self.error_lbl.setVisible(True)
