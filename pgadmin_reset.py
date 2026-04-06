import sys
import os
import sqlite3
from pathlib import Path

appdata  = Path(os.environ.get("LOCALAPPDATA", ""))
PG_DIR   = appdata / "PGOps" / "pgsql"
PA_DIR   = PG_DIR / "pgAdmin 4"
WEB_DIR  = PA_DIR / "web"
DB_PATH  = appdata / "PGOps" / "pgadmin4-data" / "pgadmin4.db"

NEW_EMAIL    = "admin@pgops.com"
NEW_PASSWORD = "pgopsadmin"

# ── Add all site-packages folders we can find under pgAdmin 4 ────────────────
for root, dirs, files in os.walk(PA_DIR):
    if Path(root).name == "site-packages":
        print(f"Adding to path: {root}")
        sys.path.insert(0, root)
    # also add Lib dir directly (some EDB builds)
    if Path(root).name in ("Lib", "lib"):
        sys.path.insert(0, root)

sys.path.insert(0, str(WEB_DIR))
os.chdir(str(WEB_DIR))

if not DB_PATH.exists():
    print(f"ERROR: Database not found at {DB_PATH}")
    sys.exit(1)

print(f"Database: {DB_PATH}")

# ── Try to hash with Flask-Security via pgAdmin's full stack ─────────────────
try:
    import config
    from pgadmin import create_app
    app = create_app()
    with app.app_context():
        from flask_security.utils import hash_password
        from pgadmin.model import db, User

        user = User.query.order_by(User.id).first()
        if not user:
            print("ERROR: No users in database.")
            sys.exit(1)

        old_email     = user.email
        user.email    = NEW_EMAIL
        user.password = hash_password(NEW_PASSWORD)
        user.active   = True
        db.session.commit()

    print(f"SUCCESS — credentials reset.")
    print(f"  Email:    {NEW_EMAIL}")
    print(f"  Password: {NEW_PASSWORD}")
    print(f"  (was: {old_email})")

except Exception as e:
    print(f"Flask-Security method failed: {e}")
    print()

    # ── Fallback: bcrypt directly into SQLite ─────────────────────────────────
    print("Trying direct bcrypt fallback…")
    try:
        import bcrypt
        hashed = bcrypt.hashpw(NEW_PASSWORD.encode(), bcrypt.gensalt(12)).decode()

        conn = sqlite3.connect(str(DB_PATH))
        cur  = conn.cursor()
        cur.execute("SELECT id, email FROM user ORDER BY id LIMIT 1")
        row = cur.fetchone()
        if not row:
            print("ERROR: No users in database.")
            conn.close()
            sys.exit(1)

        old_email = row[1]
        cur.execute(
            "UPDATE user SET email=?, password=?, active=1 WHERE id=?",
            (NEW_EMAIL, hashed, row[0])
        )
        conn.commit()
        conn.close()

        print(f"SUCCESS (bcrypt direct)")
        print(f"  Email:    {NEW_EMAIL}")
        print(f"  Password: {NEW_PASSWORD}")
        print(f"  (was: {old_email})")

    except Exception as e2:
        print(f"bcrypt fallback failed: {e2}")
        print()
        print("Both methods failed. Try this manual approach:")
        print("  1. Stop pgAdmin in PGOps")
        print(f"  2. Delete: {DB_PATH.parent}")
        print("  3. Start Server in PGOps again")
        print("  4. The new pgadmin_manager.py will reset credentials after startup")
        import traceback
        traceback.print_exc()