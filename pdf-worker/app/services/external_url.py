from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import SplitResult, urlsplit, urlunsplit

from app.config import Settings
from app.errors import AppError


TAILSCALE_NETWORK = ipaddress.ip_network("100.64.0.0/10")
Resolver = Callable[[str, int], Iterable[str]]


@dataclass(frozen=True)
class ValidatedExternalUrl:
    url: str
    hostname: str
    scheme: str
    uses_allowlist: bool
    private_http: bool


def _system_resolver(hostname: str, port: int) -> set[str]:
    return {
        item[4][0]
        for item in socket.getaddrinfo(
            hostname, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    }


def _host_matches(hostname: str, rule: str) -> bool:
    if rule.startswith("*."):
        suffix = rule[1:]
        return hostname.endswith(suffix) and hostname != rule[2:]
    return hostname == rule


def _forbidden_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if address.version == 4 and address in TAILSCALE_NETWORK:
        return "tailscale"
    if address.is_loopback:
        return "loopback"
    if address.is_link_local:
        return "link_local"
    if address.is_multicast:
        return "multicast"
    if address.is_unspecified:
        return "unspecified"
    if address.is_private:
        return "private"
    if address.is_reserved:
        return "reserved"
    return None


class ExternalUrlValidator:
    def __init__(
        self,
        settings: Settings,
        resolver: Resolver | None = None,
    ) -> None:
        self.settings = settings
        self.resolver = resolver or _system_resolver

    @staticmethod
    def hostname_hint(value: str) -> str:
        try:
            return (urlsplit(value).hostname or "未知域名").lower().rstrip(".")
        except ValueError:
            return "无效地址"

    def validate(self, value: str) -> ValidatedExternalUrl:
        if not self.settings.allow_external_urls:
            raise AppError(403, "EXTERNAL_URLS_DISABLED", "external URLs are disabled")
        url = value.strip()
        if not url or any(ord(char) < 32 or ord(char) == 127 for char in url):
            raise AppError(422, "EXTERNAL_URL_INVALID", "external URL is invalid")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise AppError(422, "EXTERNAL_URL_INVALID", "external URL is invalid") from exc
        if not parsed.scheme or not parsed.netloc:
            raise AppError(422, "EXTERNAL_URL_ABSOLUTE_REQUIRED", "external URL must be absolute")
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise AppError(422, "EXTERNAL_URL_SCHEME_BLOCKED", "external URL scheme is blocked")
        if parsed.username is not None or parsed.password is not None:
            raise AppError(422, "EXTERNAL_URL_CREDENTIALS_BLOCKED", "URL credentials are not allowed")
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if not hostname:
            raise AppError(422, "EXTERNAL_URL_HOST_REQUIRED", "external URL host is required")
        try:
            hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise AppError(422, "EXTERNAL_URL_HOST_INVALID", "external URL host is invalid") from exc
        if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
            raise AppError(422, "EXTERNAL_URL_HOST_BLOCKED", "local hostnames are not allowed")
        if any(_host_matches(hostname, rule) for rule in self.settings.external_url_blocked_hosts):
            raise AppError(422, "EXTERNAL_URL_HOST_BLOCKED", "external URL host is blocked")
        allowed_hosts = self.settings.external_url_allowed_hosts
        uses_allowlist = bool(allowed_hosts)
        if allowed_hosts and not any(_host_matches(hostname, rule) for rule in allowed_hosts):
            raise AppError(422, "EXTERNAL_URL_HOST_NOT_ALLOWED", "external URL host is not allowed")
        if scheme == "http" and self.settings.external_url_require_https:
            if not self.settings.allow_private_http_external_urls:
                raise AppError(422, "EXTERNAL_URL_HTTPS_REQUIRED", "external URL must use HTTPS")

        effective_port = port or (443 if scheme == "https" else 80)
        try:
            literal = ipaddress.ip_address(hostname)
            addresses = {str(literal)}
        except ValueError:
            try:
                addresses = set(self.resolver(hostname, effective_port))
            except OSError as exc:
                raise AppError(422, "EXTERNAL_URL_DNS_FAILED", "external URL host cannot be resolved") from exc
        if not addresses:
            raise AppError(422, "EXTERNAL_URL_DNS_FAILED", "external URL host cannot be resolved")

        private_http = False
        for raw_address in addresses:
            try:
                address = ipaddress.ip_address(raw_address)
            except ValueError as exc:
                raise AppError(422, "EXTERNAL_URL_DNS_INVALID", "DNS returned an invalid address") from exc
            reason = _forbidden_ip(address)
            if reason == "private" and scheme == "http" and self.settings.allow_private_http_external_urls:
                private_http = True
                continue
            if reason is not None:
                raise AppError(422, "EXTERNAL_URL_ADDRESS_BLOCKED", "external URL resolves to a blocked address")

        if scheme == "http" and self.settings.external_url_require_https and not private_http:
            raise AppError(422, "EXTERNAL_URL_HTTPS_REQUIRED", "external URL must use HTTPS")
        normalized_host = f"[{hostname}]" if ":" in hostname else hostname
        normalized_netloc = (
            f"{normalized_host}:{port}" if port is not None else normalized_host
        )
        normalized = SplitResult(
            scheme,
            normalized_netloc,
            parsed.path or "/",
            parsed.query,
            parsed.fragment,
        )
        return ValidatedExternalUrl(
            url=urlunsplit(normalized),
            hostname=hostname,
            scheme=scheme,
            uses_allowlist=uses_allowlist,
            private_http=private_http,
        )
