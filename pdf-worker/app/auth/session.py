from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import Settings


COOKIE_NAME = "qr_admin_session"


@dataclass(frozen=True)
class AdminSession:
    username: str
    csrf_token: str
    session_id: str


class SessionManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.serializer = URLSafeTimedSerializer(
            settings.session_secret, salt="qr-admin-session-v1"
        )

    def create(self, username: str) -> tuple[str, AdminSession]:
        session = AdminSession(username, secrets.token_urlsafe(32), secrets.token_hex(16))
        token = self.serializer.dumps(
            {"u": session.username, "c": session.csrf_token, "s": session.session_id}
        )
        return token, session

    def load(self, request: Request) -> AdminSession | None:
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return None
        try:
            payload = self.serializer.loads(
                token, max_age=self.settings.session_max_age_seconds
            )
            return AdminSession(payload["u"], payload["c"], payload["s"])
        except (BadSignature, SignatureExpired, KeyError, TypeError):
            return None

    def set_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=self.settings.session_max_age_seconds,
            httponly=True,
            secure=self.settings.session_cookie_secure,
            samesite="lax",
            path="/",
        )

    @staticmethod
    def clear_cookie(response: Response) -> None:
        response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")

    @staticmethod
    def valid_csrf(session: AdminSession, supplied: str | None) -> bool:
        return bool(supplied) and secrets.compare_digest(session.csrf_token, supplied)
