from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from app.config import Settings
from app.database import Database
from app.errors import AppError


TRACE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class ViewerSessionService:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database
        self._secret = settings.viewer_session_secret.encode("utf-8")
        self._rate_lock = threading.Lock()
        self._rate_windows: dict[tuple[int, str], deque[float]] = defaultdict(deque)
        self._page_semaphore = threading.BoundedSemaphore(
            settings.viewer_max_concurrent_page_requests
        )

    def _digest(self, purpose: str, value: str) -> str:
        return hmac.new(
            self._secret,
            f"{purpose}:{value}".encode("utf-8", errors="replace"),
            hashlib.sha256,
        ).hexdigest()

    def _new_trace(self, connection) -> str:
        for _ in range(100):
            code = "V-" + "".join(secrets.choice(TRACE_ALPHABET) for _ in range(8))
            if connection.execute(
                "SELECT 1 FROM viewer_sessions WHERE trace_code = ?", (code,)
            ).fetchone() is None:
                return code
        raise RuntimeError("could not allocate viewer trace code")

    @staticmethod
    def _event(connection, session_id: int, event_type: str, outcome: str,
               page_number: int | None = None, details: dict[str, Any] | None = None) -> None:
        connection.execute(
            """
            INSERT INTO viewer_access_events
                (viewer_session_id, event_type, page_number, outcome, created_at, details)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, event_type, page_number, outcome, iso(utc_now()),
             json.dumps(details or {}, ensure_ascii=False, separators=(",", ":"))),
        )

    def create(self, resolved, user_agent: str | None, client_host: str | None) -> tuple[str, dict[str, Any]]:
        raw_token = secrets.token_urlsafe(32)
        now = utc_now()
        expires = now + timedelta(minutes=self.settings.viewer_session_ttl_minutes)
        ua_hash = (
            self._digest("ua", user_agent or "")
            if self.settings.viewer_store_user_agent_hash and user_agent
            else None
        )
        network_hash = (
            self._digest("network", client_host or "")
            if self.settings.viewer_store_network_fingerprint and client_host
            else None
        )
        with self.database.transaction() as connection:
            trace = self._new_trace(connection)
            cursor = connection.execute(
                """
                INSERT INTO viewer_sessions
                    (session_key_hash, trace_code, qr_alias_id, revision_id,
                     created_at, expires_at, last_seen_at, status,
                     user_agent_hash, network_fingerprint_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    self._digest("token", raw_token), trace, resolved.alias["id"],
                    resolved.revision["id"], iso(now), iso(expires), iso(now),
                    ua_hash, network_hash,
                ),
            )
            session_id = int(cursor.lastrowid)
            self._event(connection, session_id, "session_created", "allowed")
        return raw_token, {
            "id": session_id,
            "trace_code": trace,
            "revision_id": resolved.revision["id"],
            "expires_at": iso(expires),
        }

    def validate(self, public_token: str, raw_token: str | None) -> dict[str, Any]:
        if not raw_token:
            raise AppError(401, "VIEWER_SESSION_REQUIRED", "viewer session is required")
        token_hash = self._digest("token", raw_token)
        now = utc_now()
        error: AppError | None = None
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT s.*, q.public_token
                FROM viewer_sessions s
                JOIN qr_aliases q ON q.id = s.qr_alias_id
                WHERE s.session_key_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if row is None:
                raise AppError(401, "VIEWER_SESSION_INVALID", "viewer session is invalid")
            session = dict(row)
            if session["public_token"] != public_token:
                connection.execute(
                    "UPDATE viewer_sessions SET denied_requests = denied_requests + 1 WHERE id = ?",
                    (session["id"],),
                )
                self._event(connection, session["id"], "page_denied", "wrong_alias")
                error = AppError(403, "VIEWER_SESSION_ALIAS_MISMATCH", "viewer session does not match this material")
            elif session["status"] != "active":
                error = AppError(403, "VIEWER_SESSION_INACTIVE", "viewer session is not active")
            else:
                absolute_expired = now >= parse_iso(session["expires_at"])
                idle_expired = now - parse_iso(session["last_seen_at"]) >= timedelta(
                    minutes=self.settings.viewer_session_idle_minutes
                )
            if error is None and (absolute_expired or idle_expired):
                connection.execute(
                    "UPDATE viewer_sessions SET status = 'expired', denied_requests = denied_requests + 1 WHERE id = ?",
                    (session["id"],),
                )
                self._event(
                    connection, session["id"], "session_expired", "idle" if idle_expired else "absolute"
                )
                error = AppError(401, "VIEWER_SESSION_EXPIRED", "viewer session has expired")
            elif error is None:
                connection.execute(
                    "UPDATE viewer_sessions SET last_seen_at = ? WHERE id = ?",
                    (iso(now), session["id"]),
                )
                session["last_seen_at"] = iso(now)
        if error is not None:
            raise error
        return session

    def _check_rate(self, session_id: int, kind: str, limit: int) -> bool:
        if not self.settings.viewer_rate_limit_enabled:
            return True
        now = time.monotonic()
        with self._rate_lock:
            window = self._rate_windows[(session_id, kind)]
            while window and window[0] <= now - 60:
                window.popleft()
            if len(window) >= limit:
                return False
            window.append(now)
            return True

    def manifest_access(self, session: dict[str, Any]) -> None:
        allowed = self._check_rate(
            session["id"], "manifest", self.settings.viewer_manifest_rate_limit_per_minute
        )
        with self.database.transaction() as connection:
            if not allowed:
                connection.execute(
                    "UPDATE viewer_sessions SET denied_requests = denied_requests + 1 WHERE id = ?",
                    (session["id"],),
                )
                self._event(connection, session["id"], "rate_limited", "manifest")
            else:
                self._event(connection, session["id"], "manifest_viewed", "allowed")
        if not allowed:
            raise AppError(429, "VIEWER_RATE_LIMITED", "too many viewer requests")

    @contextmanager
    def page_access(self, session: dict[str, Any], page_number: int) -> Iterator[None]:
        acquired = self._page_semaphore.acquire(blocking=False)
        allowed_rate = acquired and self._check_rate(
            session["id"], "page", self.settings.viewer_page_rate_limit_per_minute
        )
        allowed_total = session["page_requests"] < self.settings.viewer_session_max_page_requests
        if not acquired or not allowed_rate or not allowed_total:
            if acquired:
                self._page_semaphore.release()
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE viewer_sessions SET denied_requests = denied_requests + 1 WHERE id = ?",
                    (session["id"],),
                )
                self._event(connection, session["id"], "rate_limited", "concurrency" if not acquired else "rate_or_quota", page_number)
            raise AppError(429, "VIEWER_RATE_LIMITED", "too many viewer requests")
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    UPDATE viewer_sessions
                    SET page_requests = page_requests + 1, last_page_number = ?
                    WHERE id = ?
                    """,
                    (page_number, session["id"]),
                )
                if self.settings.viewer_log_page_events:
                    self._event(connection, session["id"], "page_viewed", "allowed", page_number)
            yield
        finally:
            self._page_semaphore.release()

    def list_sessions(self, query: str = "", limit: int = 200) -> list[dict[str, Any]]:
        pattern = f"%{query.strip()}%"
        with self.database.read() as connection:
            rows = connection.execute(
                """
                SELECT s.id, s.trace_code, s.created_at, s.expires_at, s.last_seen_at,
                       s.status, s.page_requests, s.denied_requests, s.last_page_number,
                       r.display_code AS material_code, r.name AS material_name,
                       v.revision_number, q.resolve_mode
                FROM viewer_sessions s
                JOIN qr_aliases q ON q.id = s.qr_alias_id
                JOIN answer_resources r ON r.id = q.resource_id
                JOIN answer_revisions v ON v.id = s.revision_id
                WHERE (? = '%%' OR s.trace_code LIKE ? OR r.display_code LIKE ? OR r.name LIKE ?)
                ORDER BY s.created_at DESC LIMIT ?
                """,
                (pattern, pattern, pattern, pattern, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke(self, session_id: int) -> bool:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM viewer_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                "UPDATE viewer_sessions SET status = 'revoked' WHERE id = ?", (session_id,)
            )
            self._event(connection, session_id, "session_revoked", "admin")
            return True

    def cleanup_events(self) -> int:
        cutoff = iso(utc_now() - timedelta(days=self.settings.viewer_access_event_retention_days))
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM viewer_access_events WHERE created_at < ?", (cutoff,)
            )
            return cursor.rowcount
