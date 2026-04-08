#!/usr/bin/env python3
"""
pgops_cli.py
Command-line interface for PGOps.
Communicates with the running PGOps app via http://127.0.0.1:7420/api.

Usage:
  pgops apps
  pgops deploy --zip ./app.zip --name inventory [--display "Inventory Manager"]
  pgops deploy --git https://github.com/org/app.git --name inventory [--branch main]
  pgops start <app>
  pgops stop <app>
  pgops restart <app>
  pgops pull <app>
  pgops logs <app> [--lines 100]
  pgops delete <app>
  pgops db:create <name> <username> [--password <pw>]
  pgops db:list
  pgops backup <database>
  pgops status
"""

import argparse
import json
import os
import sys
import secrets
import string

PGOPS_API = "http://127.0.0.1:7420/api"

# ── ANSI colours (disabled on Windows if not supported) ───────────────────────
_use_colour = sys.platform != "win32" or "ANSICON" in os.environ

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _use_colour else text

def green(t):  return _c(t, "32")
def red(t):    return _c(t, "31")
def yellow(t): return _c(t, "33")
def blue(t):   return _c(t, "34")
def bold(t):   return _c(t, "1")
def dim(t):    return _c(t, "2")


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _check_running():
    try:
        import urllib.request
        urllib.request.urlopen(f"{PGOPS_API}/status", timeout=2)
    except Exception:
        print(red("Error: PGOps is not running."))
        print(dim("  Start PGOps and try again."))
        sys.exit(1)


def _get(path: str) -> dict:
    import urllib.request, urllib.error
    try:
        with urllib.request.urlopen(f"{PGOPS_API}{path}", timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        data = json.loads(exc.read())
        print(red(f"Error: {data.get('error', exc)}"))
        sys.exit(1)
    except Exception as exc:
        print(red(f"Request failed: {exc}"))
        sys.exit(1)


def _post(path: str, payload: dict = None) -> dict:
    import urllib.request, urllib.error
    body = json.dumps(payload or {}).encode()
    req  = urllib.request.Request(
        f"{PGOPS_API}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        data = json.loads(exc.read())
        print(red(f"Error: {data.get('error', exc)}"))
        sys.exit(1)
    except Exception as exc:
        print(red(f"Request failed: {exc}"))
        sys.exit(1)


def _delete(path: str) -> dict:
    import urllib.request, urllib.error
    req = urllib.request.Request(
        f"{PGOPS_API}{path}", method="DELETE"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        data = json.loads(exc.read())
        print(red(f"Error: {data.get('error', exc)}"))
        sys.exit(1)
    except Exception as exc:
        print(red(f"Request failed: {exc}"))
        sys.exit(1)


def _print_steps(steps: list):
    icon_map  = {"running": yellow("⏳"), "done": green("✓"), "error": red("✗")}
    for s in steps:
        icon = icon_map.get(s.get("status", ""), "·")
        print(f"  {icon}  {s['step']}")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_status(args):
    _check_running()
    data = _get("/status")
    print(bold("PGOps Status"))
    for key, val in data.items():
        if isinstance(val, bool):
            label = green("running") if val else red("stopped")
        else:
            label = str(val)
        print(f"  {key:<12} {label}")


def cmd_apps(args):
    _check_running()
    data = _get("/apps")
    apps = data.get("apps", [])
    if not apps:
        print(dim("  No apps deployed."))
        return
    print(bold(f"{'NAME':<22} {'DOMAIN':<36} {'STATUS':<10} {'PORT'}"))
    print(dim("─" * 80))
    for app in apps:
        status = app.get("status", "stopped")
        dot    = green("●") if status == "running" else red("●")
        print(
            f"  {dot} {app['id']:<20} "
            f"{app.get('domain',''):<36} "
            f"{status:<10} "
            f"{app.get('internal_port','')}"
        )


def cmd_deploy(args):
    _check_running()
    payload = {
        "slug":         args.name.strip().lower(),
        "display_name": args.display or args.name,
    }

    if args.zip:
        if not os.path.isfile(args.zip):
            print(red(f"ZIP file not found: {args.zip}"))
            sys.exit(1)
        payload["source_type"] = "zip"
        payload["source_path"] = os.path.abspath(args.zip)
    elif args.git:
        payload["source_type"] = "git"
        payload["source_path"] = args.git
        payload["git_branch"]  = args.branch or "main"
    else:
        print(red("Provide --zip or --git."))
        sys.exit(1)

    print(bold(f"Deploying '{payload['display_name']}'…"))
    data = _post("/apps/deploy", payload)
    _print_steps(data.get("steps", []))
    app = data.get("app", {})
    if app:
        print()
        print(green(bold("✓ Deployment complete!")))
        domain = app.get("domain", "")
        print(f"  URL: {blue('http://' + domain)}")


def cmd_start(args):
    _check_running()
    data = _post(f"/apps/{args.app}/start")
    ok = data.get("ok", False)
    msg = data.get("message", "")
    print(green(f"✓ {msg}") if ok else red(f"✗ {msg}"))


def cmd_stop(args):
    _check_running()
    data = _post(f"/apps/{args.app}/stop")
    ok = data.get("ok", False)
    msg = data.get("message", "")
    print(green(f"✓ {msg}") if ok else red(f"✗ {msg}"))


def cmd_restart(args):
    _check_running()
    data = _post(f"/apps/{args.app}/restart")
    ok = data.get("ok", False)
    msg = data.get("message", "")
    print(green(f"✓ {msg}") if ok else red(f"✗ {msg}"))


def cmd_pull(args):
    _check_running()
    print(bold(f"Pulling latest for '{args.app}'…"))
    data = _post(f"/apps/{args.app}/pull")
    _print_steps(data.get("steps", []))
    ok  = data.get("ok", False)
    msg = data.get("message", "")
    print(green(f"\n✓ {msg}") if ok else red(f"\n✗ {msg}"))


def cmd_logs(args):
    _check_running()
    n    = getattr(args, "lines", 100) or 100
    data = _get(f"/apps/{args.app}/logs?lines={n}")
    lines = data.get("lines", [])
    if not lines:
        print(dim(f"  No logs for '{args.app}'."))
        return
    for line in lines:
        print(line, end="")


def cmd_delete(args):
    _check_running()
    print(red(bold(
        f"This will permanently delete '{args.app}' including its database and files."
    )))
    confirm = input("Type the app name to confirm: ").strip()
    if confirm != args.app:
        print(dim("Cancelled."))
        return
    print(bold(f"Deleting '{args.app}'…"))
    data = _delete(f"/apps/{args.app}")
    _print_steps(data.get("steps", []))
    print(green("\n✓ Deleted."))


def cmd_db_create(args):
    _check_running()
    pw = getattr(args, "password", None) or "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(20)
    )
    data = _post("/db/create", {
        "name":     args.name,
        "username": args.username,
        "password": pw,
    })
    ok  = data.get("ok", False)
    msg = data.get("message", "")
    if ok:
        print(green(f"✓ {msg}"))
        print(f"  Password: {yellow(pw)}")
    else:
        print(red(f"✗ {msg}"))


def cmd_db_list(args):
    _check_running()
    data = _get("/db/list")
    dbs  = data.get("databases", [])
    if not dbs:
        print(dim("  No databases."))
        return
    print(bold(f"{'DATABASE':<30} OWNER"))
    print(dim("─" * 50))
    for db in dbs:
        print(f"  {db.get('name',''):<30} {db.get('owner','')}")


def cmd_backup(args):
    _check_running()
    print(bold(f"Backing up '{args.database}'…"))
    data = _post(f"/backup/{args.database}")
    ok   = data.get("ok", False)
    msg  = data.get("message", "")
    file = data.get("file", "")
    if ok:
        print(green(f"✓ {msg}"))
        if file:
            print(f"  File: {dim(file)}")
    else:
        print(red(f"✗ {msg}"))


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgops",
        description="PGOps CLI — manage your local PostgreSQL + app server",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # status
    sub.add_parser("status", help="Show PGOps service status")

    # apps
    sub.add_parser("apps", help="List all deployed apps")

    # deploy
    dp = sub.add_parser("deploy", help="Deploy a new Laravel app")
    dp.add_argument("--zip",     help="Path to ZIP archive")
    dp.add_argument("--git",     help="Git repository URL")
    dp.add_argument("--branch",  default="main", help="Git branch (default: main)")
    dp.add_argument("--name",    required=True, help="App slug (e.g. inventory)")
    dp.add_argument("--display", help="Display name (e.g. 'Inventory Manager')")

    # start / stop / restart / pull / logs / delete
    for cmd_name, help_text in [
        ("start",   "Start a stopped app"),
        ("stop",    "Stop a running app"),
        ("restart", "Restart an app"),
        ("pull",    "Git pull + migrate + restart"),
        ("delete",  "Delete an app and all its data"),
    ]:
        p = sub.add_parser(cmd_name, help=help_text)
        p.add_argument("app", help="App slug")

    lp = sub.add_parser("logs", help="Show app logs")
    lp.add_argument("app", help="App slug")
    lp.add_argument("--lines", type=int, default=100, help="Number of lines (default: 100)")

    # db:create / db:list
    dbc = sub.add_parser("db:create", help="Create a database and user")
    dbc.add_argument("name",     help="Database name")
    dbc.add_argument("username", help="Owner username")
    dbc.add_argument("--password", help="Password (auto-generated if omitted)")

    sub.add_parser("db:list", help="List all databases")

    # backup
    bk = sub.add_parser("backup", help="Backup a database")
    bk.add_argument("database", help="Database name")

    return parser


def main():
    parser = build_parser()
    args   = parser.parse_args()

    dispatch = {
        "status":    cmd_status,
        "apps":      cmd_apps,
        "deploy":    cmd_deploy,
        "start":     cmd_start,
        "stop":      cmd_stop,
        "restart":   cmd_restart,
        "pull":      cmd_pull,
        "logs":      cmd_logs,
        "delete":    cmd_delete,
        "db:create": cmd_db_create,
        "db:list":   cmd_db_list,
        "backup":    cmd_backup,
    }

    if args.command in dispatch:
        dispatch[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
