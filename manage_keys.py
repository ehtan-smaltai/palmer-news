"""API key management CLI for the Palmer News API.

Usage:
  python manage_keys.py create "some label"   -> prints a new key
  python manage_keys.py list                  -> lists all keys + usage
  python manage_keys.py revoke <key>          -> deactivates a key
"""
from __future__ import annotations

import secrets
import sys
from datetime import datetime, timezone

from store import create_api_key, get_conn, list_api_keys, revoke_api_key


def new_key() -> str:
    return "pn_" + secrets.token_urlsafe(32)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return

    conn = get_conn()
    cmd = sys.argv[1]

    if cmd == "create":
        label = sys.argv[2] if len(sys.argv) > 2 else "unlabeled"
        key = new_key()
        create_api_key(conn, key, label)
        print(f"Created key for '{label}':\n  {key}\n"
              f"Store this now — it isn't shown again by 'list' (only a masked version).")

    elif cmd == "list":
        keys = list_api_keys(conn)
        if not keys:
            print("No API keys yet.")
            return
        for k in keys:
            masked = k["api_key"][:6] + "..." + k["api_key"][-4:]
            created = datetime.fromtimestamp(k["created_at"], tz=timezone.utc).strftime("%Y-%m-%d")
            last_used = (datetime.fromtimestamp(k["last_used_at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                         if k["last_used_at"] else "never")
            status = "active" if k["active"] else "REVOKED"
            print(f"  {masked}  [{status}]  label={k['label']!r}  created={created}  "
                  f"requests={k['request_count']}  last_used={last_used}")

    elif cmd == "revoke":
        if len(sys.argv) < 3:
            print("Usage: python manage_keys.py revoke <full-key>")
            return
        ok = revoke_api_key(conn, sys.argv[2])
        print("Revoked." if ok else "Key not found.")

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
