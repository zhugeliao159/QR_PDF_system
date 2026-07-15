from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class NetworkStatus:
    kind: str
    label: str
    message: str
    tone: str
    requires_test_confirmation: bool


def classify_public_url(url: str) -> NetworkStatus:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return NetworkStatus(
            "local", "本机测试地址",
            "当前二维码地址仅能在本机测试，手机扫码无法访问。请勿用于正式印刷。",
            "danger", True,
        )
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and address in ipaddress.ip_network("100.64.0.0/10"):
        return NetworkStatus(
            "tailscale", "Tailscale 测试地址",
            "当前二维码仅可供已加入同一 Tailscale 网络的设备访问，不适合普通学生使用。",
            "warning", True,
        )
    if address and address.is_private:
        return NetworkStatus(
            "lan", "机构内网地址",
            "当前二维码仅可在机构局域网内访问，学生离开该网络后将无法打开。",
            "warning", True,
        )
    if parsed.scheme != "https":
        return NetworkStatus(
            "public-http", "非加密外部地址",
            "当前地址可能可以从外部访问，但未启用 HTTPS，不建议用于正式发布。",
            "warning", True,
        )
    return NetworkStatus(
        "public-https", "公网正式地址",
        "当前二维码使用 HTTPS 公网地址，仍需确认域名、权限和备份后再用于正式印刷。",
        "success", False,
    )
