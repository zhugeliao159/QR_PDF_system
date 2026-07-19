from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "true" if default else "false").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _env_hosts(name: str) -> tuple[str, ...]:
    values = []
    for item in os.getenv(name, "").split(","):
        value = item.strip().lower().rstrip(".")
        if value:
            values.append(value)
    return tuple(dict.fromkeys(values))


def _env_choice(name: str, default: str, allowed: set[str]) -> str:
    value = os.getenv(name, default).strip().lower() or default
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of: {choices}")
    return value


@dataclass(frozen=True)
class Settings:
    public_base_url: str
    max_upload_size_mb: int
    max_pdf_pages: int
    max_binding_versions: int
    default_qr_size_mm: float
    default_qr_margin_mm: float
    database_path: Path
    storage_root: Path
    input_dir: Path
    output_dir: Path
    site_name: str = "练习册二维码管理系统"
    admin_username: str = "admin"
    admin_password_hash: str = ""
    deletion_password_hash: str = ""
    admin_api_token_hash: str = ""
    session_secret: str = "test-session-secret-change-in-production-32-bytes"
    session_cookie_secure: bool = False
    session_max_age_seconds: int = 28800
    enable_admin_api_docs: bool = False
    max_image_size_mb: int = 30
    max_image_pixels: int = 40_000_000
    allow_external_urls: bool = False
    allow_private_http_external_urls: bool = False
    external_url_allowed_hosts: tuple[str, ...] = ()
    external_url_blocked_hosts: tuple[str, ...] = ()
    external_url_require_https: bool = True
    preview_dpi: int = 144
    preview_webp_quality: int = 82
    preview_webp_method: int = 4
    preview_max_pages: int = 500
    preview_max_render_width: int = 2000
    preview_render_version: str = "v1"
    preview_job_max_attempts: int = 2
    preview_job_stale_seconds: int = 900
    preview_worker_poll_seconds: float = 2.0
    batch_upload_max_files: int = 100
    batch_upload_max_total_mb: int = 2048
    batch_import_stale_seconds: int = 900
    require_preview_before_publish: bool = False
    protected_preview_external_url_policy: str = "disable"
    viewer_session_ttl_minutes: int = 30
    viewer_session_idle_minutes: int = 10
    viewer_cookie_secure: bool = False
    viewer_cookie_name: str = "viewer_session"
    viewer_session_secret: str = "test-viewer-session-secret-at-least-32-bytes"
    viewer_session_max_page_requests: int = 1000
    viewer_store_network_fingerprint: bool = False
    viewer_store_user_agent_hash: bool = True
    viewer_access_event_retention_days: int = 30
    viewer_session_retention_days: int = 7
    audit_event_retention_days: int = 180
    viewer_log_page_events: bool = True
    viewer_page_rate_limit_per_minute: int = 120
    viewer_manifest_rate_limit_per_minute: int = 30
    viewer_max_concurrent_page_requests: int = 6
    viewer_rate_limit_enabled: bool = True
    watermark_font_path: str = ""
    watermark_text_template: str = "在线预览 | {material_code} | {trace_code} | {timestamp}"
    watermark_opacity: int = 45
    watermark_rotation_degrees: int = -25
    watermark_font_size: int = 28
    watermark_spacing_x: int = 420
    watermark_spacing_y: int = 280

    @classmethod
    def from_env(cls) -> "Settings":
        public_base_url = os.getenv(
            "PUBLIC_QR_BASE_URL",
            os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:18081"),
        ).rstrip("/")
        parsed = urlparse(public_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("PUBLIC_BASE_URL must be an absolute http(s) URL")
        if parsed.query or parsed.fragment:
            raise ValueError("PUBLIC_BASE_URL cannot include a query or fragment")

        settings = cls(
            public_base_url=public_base_url,
            max_upload_size_mb=_env_int("MAX_UPLOAD_SIZE_MB", 100),
            max_pdf_pages=_env_int("MAX_PDF_PAGES", 500),
            max_binding_versions=_env_int("MAX_BINDING_VERSIONS", 5),
            default_qr_size_mm=_env_float("DEFAULT_QR_SIZE_MM", 20, 0.1),
            default_qr_margin_mm=_env_float("DEFAULT_QR_MARGIN_MM", 10),
            database_path=Path(
                os.getenv("PDF_WORKER_DATABASE_PATH", "/data/db/app.db")
            ),
            storage_root=Path(
                os.getenv("PDF_WORKER_STORAGE_ROOT", "/data/storage")
            ),
            input_dir=Path(os.getenv("PDF_INPUT_DIR", "/data/input")),
            output_dir=Path(os.getenv("PDF_OUTPUT_DIR", "/data/output")),
            site_name=os.getenv("SITE_NAME", "练习册二维码管理系统").strip()
            or "练习册二维码管理系统",
            admin_username=os.getenv("ADMIN_USERNAME", "admin").strip() or "admin",
            admin_password_hash=os.getenv("ADMIN_PASSWORD_HASH", "").strip(),
            deletion_password_hash=os.getenv("DELETION_PASSWORD_HASH", "").strip(),
            admin_api_token_hash=os.getenv("ADMIN_API_TOKEN_HASH", "").strip(),
            session_secret=os.getenv("SESSION_SECRET", "").strip(),
            session_cookie_secure=_env_bool("SESSION_COOKIE_SECURE", False),
            session_max_age_seconds=_env_int("SESSION_MAX_AGE_SECONDS", 28800, 300),
            enable_admin_api_docs=_env_bool("ENABLE_ADMIN_API_DOCS", False),
            max_image_size_mb=_env_int("MAX_IMAGE_SIZE_MB", 30),
            max_image_pixels=_env_int("MAX_IMAGE_PIXELS", 40_000_000),
            allow_external_urls=_env_bool("ALLOW_EXTERNAL_URLS", False),
            allow_private_http_external_urls=_env_bool(
                "ALLOW_PRIVATE_HTTP_EXTERNAL_URLS", False
            ),
            external_url_allowed_hosts=_env_hosts("EXTERNAL_URL_ALLOWED_HOSTS"),
            external_url_blocked_hosts=_env_hosts("EXTERNAL_URL_BLOCKED_HOSTS"),
            external_url_require_https=_env_bool(
                "EXTERNAL_URL_REQUIRE_HTTPS", True
            ),
            preview_dpi=_env_int("PREVIEW_DPI", 144),
            preview_webp_quality=_env_int("PREVIEW_WEBP_QUALITY", 82, 1),
            preview_webp_method=_env_int("PREVIEW_WEBP_METHOD", 4, 0),
            preview_max_pages=_env_int("PREVIEW_MAX_PAGES", 500),
            preview_max_render_width=_env_int("PREVIEW_MAX_RENDER_WIDTH", 2000),
            preview_render_version=os.getenv("PREVIEW_RENDER_VERSION", "v1").strip() or "v1",
            preview_job_max_attempts=_env_int("PREVIEW_JOB_MAX_ATTEMPTS", 2),
            preview_job_stale_seconds=_env_int("PREVIEW_JOB_STALE_SECONDS", 900),
            preview_worker_poll_seconds=_env_float("PREVIEW_WORKER_POLL_SECONDS", 2.0, 0.1),
            batch_upload_max_files=_env_int("BATCH_UPLOAD_MAX_FILES", 100),
            batch_upload_max_total_mb=_env_int("BATCH_UPLOAD_MAX_TOTAL_MB", 2048),
            batch_import_stale_seconds=_env_int("BATCH_IMPORT_STALE_SECONDS", 900, 60),
            require_preview_before_publish=_env_bool(
                "REQUIRE_PREVIEW_BEFORE_PUBLISH", True
            ),
            protected_preview_external_url_policy=_env_choice(
                "PROTECTED_PREVIEW_EXTERNAL_URL_POLICY",
                "disable",
                {"disable", "warn", "allow"},
            ),
            viewer_session_ttl_minutes=_env_int("VIEWER_SESSION_TTL_MINUTES", 30),
            viewer_session_idle_minutes=_env_int("VIEWER_SESSION_IDLE_MINUTES", 10),
            viewer_cookie_secure=_env_bool("VIEWER_COOKIE_SECURE", False),
            viewer_cookie_name=os.getenv("VIEWER_COOKIE_NAME", "viewer_session").strip() or "viewer_session",
            viewer_session_secret=os.getenv("VIEWER_SESSION_SECRET", "").strip(),
            viewer_session_max_page_requests=_env_int("VIEWER_SESSION_MAX_PAGE_REQUESTS", 1000),
            viewer_store_network_fingerprint=_env_bool("VIEWER_STORE_NETWORK_FINGERPRINT", False),
            viewer_store_user_agent_hash=_env_bool("VIEWER_STORE_USER_AGENT_HASH", True),
            viewer_access_event_retention_days=_env_int("VIEWER_ACCESS_EVENT_RETENTION_DAYS", 30),
            viewer_session_retention_days=_env_int("VIEWER_SESSION_RETENTION_DAYS", 7),
            audit_event_retention_days=_env_int("AUDIT_EVENT_RETENTION_DAYS", 180),
            viewer_log_page_events=_env_bool("VIEWER_LOG_PAGE_EVENTS", True),
            viewer_page_rate_limit_per_minute=_env_int("VIEWER_PAGE_RATE_LIMIT_PER_MINUTE", 120),
            viewer_manifest_rate_limit_per_minute=_env_int("VIEWER_MANIFEST_RATE_LIMIT_PER_MINUTE", 30),
            viewer_max_concurrent_page_requests=_env_int("VIEWER_MAX_CONCURRENT_PAGE_REQUESTS", 6),
            viewer_rate_limit_enabled=_env_bool("VIEWER_RATE_LIMIT_ENABLED", True),
            watermark_font_path=os.getenv("WATERMARK_FONT_PATH", "").strip(),
            watermark_text_template=os.getenv(
                "WATERMARK_TEXT_TEMPLATE",
                "在线预览 | {material_code} | {trace_code} | {timestamp}",
            ).strip() or "在线预览 | {material_code} | {trace_code} | {timestamp}",
            watermark_opacity=_env_int("WATERMARK_OPACITY", 45, 1),
            watermark_rotation_degrees=int(os.getenv("WATERMARK_ROTATION_DEGREES", "-25")),
            watermark_font_size=_env_int("WATERMARK_FONT_SIZE", 28),
            watermark_spacing_x=_env_int("WATERMARK_SPACING_X", 420),
            watermark_spacing_y=_env_int("WATERMARK_SPACING_Y", 280),
        )
        if not settings.admin_password_hash:
            raise ValueError("ADMIN_PASSWORD_HASH must be configured")
        if len(settings.session_secret) < 32:
            raise ValueError("SESSION_SECRET must contain at least 32 characters")
        if len(settings.viewer_session_secret.encode("utf-8")) < 32:
            raise ValueError("VIEWER_SESSION_SECRET must contain at least 32 bytes")
        if settings.viewer_session_idle_minutes > settings.viewer_session_ttl_minutes:
            raise ValueError("VIEWER_SESSION_IDLE_MINUTES cannot exceed VIEWER_SESSION_TTL_MINUTES")
        if not 1 <= settings.watermark_opacity <= 255:
            raise ValueError("WATERMARK_OPACITY must be between 1 and 255")
        return settings

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def max_image_size_bytes(self) -> int:
        return self.max_image_size_mb * 1024 * 1024

    @property
    def batch_upload_max_total_bytes(self) -> int:
        return self.batch_upload_max_total_mb * 1024 * 1024

    @property
    def bindings_dir(self) -> Path:
        return self.storage_root / "bindings"

    @property
    def source_pdfs_dir(self) -> Path:
        return self.storage_root / "source-pdfs"

    @property
    def generated_pdfs_dir(self) -> Path:
        return self.storage_root / "generated-pdfs"

    @property
    def previews_dir(self) -> Path:
        return self.storage_root / "previews"

    @property
    def batch_imports_dir(self) -> Path:
        return self.storage_root / "batch-imports"

    @property
    def trash_dir(self) -> Path:
        return self.storage_root / ".trash"

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        for path in (
            self.storage_root,
            self.bindings_dir,
            self.source_pdfs_dir,
            self.generated_pdfs_dir,
            self.previews_dir,
            self.batch_imports_dir,
            self.trash_dir,
            self.input_dir,
            self.output_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
