"""Optional user accounts (SQLite, scrypt password hashes, signed tokens).

Everything works without an account; accounts add history and a personal workspace.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .config import Settings
from .errors import AppError, Forbidden, InvalidRequest, NotFound, Unauthorized
from .signing import make_token, read_token

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL COLLATE NOCASE,
  pw_hash TEXT NOT NULL, created REAL NOT NULL, token_version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, op TEXT NOT NULL, status TEXT NOT NULL,
  created REAL NOT NULL, outputs TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS history_user ON history(user_id, created DESC);
CREATE TABLE IF NOT EXISTS saved_files (
  id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL,
  kind TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS resets (
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires REAL NOT NULL
);
"""
SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, dk = stored.split("$")
        if scheme != "scrypt":
            return False
        cand = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **SCRYPT)
        return hmac.compare_digest(cand, bytes.fromhex(dk))
    except (ValueError, TypeError):
        return False


class AuthService:
    def __init__(self, settings: Settings):
        self.s = settings
        with self._db() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _db(self):
        con = sqlite3.connect(self.s.db_path, timeout=15)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------------ users
    @staticmethod
    def _check_password_strength(pw: str) -> None:
        if len(pw) < 8:
            raise InvalidRequest("Password must be at least 8 characters.", "weak_password")
        if len(pw) > 200:
            raise InvalidRequest("Password is too long.", "weak_password")

    def register(self, email: str, password: str) -> dict:
        email = (email or "").strip()
        if not EMAIL_RE.match(email):
            raise InvalidRequest("Enter a valid email address.", "invalid_email")
        self._check_password_strength(password)
        try:
            with self._db() as db:
                cur = db.execute("INSERT INTO users(email, pw_hash, created) VALUES (?,?,?)",
                                 (email, hash_password(password), time.time()))
                uid = cur.lastrowid
        except sqlite3.IntegrityError:
            raise AppError("email_taken", "An account with this email already exists.", 409)
        return self._session(uid, email, 0)

    def login(self, email: str, password: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT * FROM users WHERE email=?", ((email or "").strip(),)).fetchone()
        ok = verify_password(password or "", row["pw_hash"] if row else hash_password("x"))  # constant-ish time
        if not row or not ok:
            raise Unauthorized("Incorrect email or password.", "bad_credentials")
        return self._session(row["id"], row["email"], row["token_version"])

    def _session(self, uid: int, email: str, version: int) -> dict:
        ttl = self.s.auth_token_ttl_hours * 3600
        token = make_token(self.s.secret_key, {"uid": uid, "v": version}, ttl)
        return {"token": token, "user": {"id": uid, "email": email}}

    def user_from_token(self, token: str | None) -> dict | None:
        data = read_token(self.s.secret_key, token)
        if not data or "uid" not in data:
            return None
        with self._db() as db:
            row = db.execute("SELECT id, email, token_version FROM users WHERE id=?", (data["uid"],)).fetchone()
        if not row or row["token_version"] != data.get("v"):
            return None
        return {"id": row["id"], "email": row["email"]}

    def change_password(self, uid: int, old: str, new: str) -> dict:
        self._check_password_strength(new)
        with self._db() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not row or not verify_password(old or "", row["pw_hash"]):
                raise Unauthorized("Current password is incorrect.", "bad_credentials")
            version = row["token_version"] + 1  # invalidates every older token
            db.execute("UPDATE users SET pw_hash=?, token_version=? WHERE id=?", (hash_password(new), version, uid))
        return self._session(uid, row["email"], version)

    def delete_account(self, uid: int, password: str) -> None:
        with self._db() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not row or not verify_password(password or "", row["pw_hash"]):
                raise Unauthorized("Password is incorrect.", "bad_credentials")
            db.execute("DELETE FROM history WHERE user_id=?", (uid,))
            db.execute("DELETE FROM saved_files WHERE user_id=?", (uid,))
            db.execute("DELETE FROM resets WHERE user_id=?", (uid,))
            db.execute("DELETE FROM users WHERE id=?", (uid,))
        shutil.rmtree(self.s.user_files_dir / str(uid), ignore_errors=True)

    # ---------------------------------------------------------- password reset
    def request_reset(self, email: str) -> str | None:
        """Returns the raw reset token (or None for unknown emails). The HTTP layer never
        reveals which; delivery by email must be wired up by the operator."""
        with self._db() as db:
            row = db.execute("SELECT id FROM users WHERE email=?", ((email or "").strip(),)).fetchone()
            if not row:
                return None
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO resets VALUES (?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), row["id"], time.time() + 1800))
        return token

    def reset_password(self, token: str, new: str) -> None:
        self._check_password_strength(new)
        th = hashlib.sha256((token or "").encode()).hexdigest()
        with self._db() as db:
            row = db.execute("SELECT * FROM resets WHERE token_hash=?", (th,)).fetchone()
            if not row or row["expires"] < time.time():
                raise InvalidRequest("This reset link is invalid or has expired.", "invalid_reset")
            db.execute("DELETE FROM resets WHERE token_hash=?", (th,))
            db.execute("UPDATE users SET pw_hash=?, token_version=token_version+1 WHERE id=?",
                       (hash_password(new), row["user_id"]))

    # ----------------------------------------------------------------- history
    def add_history(self, uid: int, op: str, status: str, outputs: list[dict]) -> None:
        import json

        slim = [{"id": o["id"], "name": o["name"], "size": o["size"]} for o in outputs]
        with self._db() as db:
            db.execute("INSERT INTO history(user_id, op, status, created, outputs) VALUES (?,?,?,?,?)",
                       (uid, op, status, time.time(), json.dumps(slim)))
            db.execute("DELETE FROM history WHERE user_id=? AND id NOT IN "
                       "(SELECT id FROM history WHERE user_id=? ORDER BY created DESC LIMIT 200)", (uid, uid))

    def list_history(self, uid: int, limit: int = 50) -> list[dict]:
        import json

        with self._db() as db:
            rows = db.execute("SELECT * FROM history WHERE user_id=? ORDER BY created DESC LIMIT ?", (uid, limit)).fetchall()
        return [{"id": r["id"], "op": r["op"], "status": r["status"], "created": r["created"],
                 "outputs": json.loads(r["outputs"])} for r in rows]

    def clear_history(self, uid: int) -> None:
        with self._db() as db:
            db.execute("DELETE FROM history WHERE user_id=?", (uid,))

    # ------------------------------------------------------- personal workspace
    def save_file(self, uid: int, src: Path, file_id: str, name: str, size: int, kind: str) -> dict:
        d = self.s.user_files_dir / str(uid)
        d.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            n = db.execute("SELECT COUNT(*) FROM saved_files WHERE user_id=?", (uid,)).fetchone()[0]
            if n >= 200:
                raise InvalidRequest("Your workspace is full (200 files). Delete some first.", "workspace_full")
            shutil.copyfile(src, d / file_id)
            db.execute("INSERT OR REPLACE INTO saved_files VALUES (?,?,?,?,?,?)", (file_id, uid, name, size, kind, time.time()))
        return {"id": file_id, "name": name, "size": size, "kind": kind}

    def list_saved(self, uid: int) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM saved_files WHERE user_id=? ORDER BY created DESC", (uid,)).fetchall()
        return [{"id": r["id"], "name": r["name"], "size": r["size"], "kind": r["kind"], "created": r["created"]} for r in rows]

    def saved_path(self, uid: int, file_id: str) -> tuple[Path, dict]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{22,64}", file_id or ""):
            raise NotFound("File not found", "file_not_found")
        with self._db() as db:
            row = db.execute("SELECT * FROM saved_files WHERE id=? AND user_id=?", (file_id, uid)).fetchone()
        p = self.s.user_files_dir / str(uid) / file_id
        if not row or not p.exists():
            raise NotFound("File not found", "file_not_found")
        return p, dict(row)

    def delete_saved(self, uid: int, file_id: str) -> None:
        p, _ = self.saved_path(uid, file_id)
        with self._db() as db:
            db.execute("DELETE FROM saved_files WHERE id=? AND user_id=?", (file_id, uid))
        p.unlink(missing_ok=True)
