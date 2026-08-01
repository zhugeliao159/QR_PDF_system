from __future__ import annotations

from dataclasses import dataclass

from app.auth.password import verify_password
from app.config import Settings
from app.database import Database
from app.models import utc_now_iso


ADMIN_PASSWORD = "admin_password"
DELETION_PASSWORD = "deletion_password"


@dataclass(frozen=True)
class StoredCredential:
    password_hash: str
    revision: int


class CredentialService:
    """Read environment defaults and persist web-managed password overrides."""

    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database

    def _fallback(self, credential_key: str) -> StoredCredential:
        if credential_key == ADMIN_PASSWORD:
            return StoredCredential(self.settings.admin_password_hash, 0)
        if credential_key == DELETION_PASSWORD:
            return StoredCredential(self.settings.deletion_password_hash, 0)
        raise ValueError("unsupported credential key")

    def _get(self, credential_key: str) -> StoredCredential:
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT password_hash, revision
                FROM security_credentials
                WHERE credential_key = ?
                """,
                (credential_key,),
            ).fetchone()
        if row is None:
            return self._fallback(credential_key)
        return StoredCredential(str(row["password_hash"]), int(row["revision"]))

    def admin_password_hash(self) -> str:
        return self._get(ADMIN_PASSWORD).password_hash

    def admin_revision(self) -> int:
        return self._get(ADMIN_PASSWORD).revision

    def deletion_password_hash(self) -> str:
        return self._get(DELETION_PASSWORD).password_hash

    def deletion_password_configured(self) -> bool:
        return bool(self.deletion_password_hash())

    def verify_admin(self, supplied: str) -> bool:
        return verify_password(supplied, self.admin_password_hash())

    def verify_deletion(self, supplied: str) -> bool:
        password_hash = self.deletion_password_hash()
        return bool(password_hash) and verify_password(supplied, password_hash)

    def update(self, credential_key: str, password_hash: str, actor: str) -> int:
        if credential_key not in {ADMIN_PASSWORD, DELETION_PASSWORD}:
            raise ValueError("unsupported credential key")
        if not password_hash:
            raise ValueError("password hash is required")
        timestamp = utc_now_iso()
        event_type = (
            "admin_password_changed"
            if credential_key == ADMIN_PASSWORD
            else "deletion_password_changed"
        )
        summary = (
            "管理员登录密码已通过后台修改"
            if credential_key == ADMIN_PASSWORD
            else "永久删除二级密码已通过后台修改"
        )
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT revision FROM security_credentials WHERE credential_key = ?",
                (credential_key,),
            ).fetchone()
            revision = (int(row["revision"]) + 1) if row is not None else 1
            connection.execute(
                """
                INSERT INTO security_credentials
                    (credential_key, password_hash, revision, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(credential_key) DO UPDATE SET
                    password_hash = excluded.password_hash,
                    revision = excluded.revision,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (credential_key, password_hash, revision, actor, timestamp),
            )
            connection.execute(
                """
                INSERT INTO audit_events (event_type, actor, summary, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (event_type, actor, summary, timestamp),
            )
        return revision
