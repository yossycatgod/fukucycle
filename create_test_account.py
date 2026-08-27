"""Create or refresh the non-personal account supplied to contest reviewers."""

import hashlib
import json
import secrets
from pathlib import Path


USERNAME = "fukucycle_judge"
PASSWORD = "FukuCycleDemo2026!"
USERS_FILE = Path(__file__).with_name("m3ow_users.json")


def main() -> None:
    try:
        users = json.loads(USERS_FILE.read_text(encoding="utf-8")) if USERS_FILE.exists() else {}
    except (OSError, json.JSONDecodeError):
        users = {}
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", PASSWORD.encode(), bytes.fromhex(salt), 200_000
    ).hex()
    users[USERNAME] = {
        "display_name": "審査用 Explorer",
        "salt": salt,
        "password_hash": digest,
    }
    USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Created test account: {USERNAME}")


if __name__ == "__main__":
    main()
