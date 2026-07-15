import pytest

from app.network import classify_public_url


@pytest.mark.parametrize(
    ("url", "kind", "text"),
    [
        ("http://127.0.0.1:18081", "local", "手机扫码无法访问"),
        ("http://localhost:18081", "local", "本机测试"),
        ("http://192.168.1.10:18081", "lan", "局域网"),
        ("http://10.0.0.5", "lan", "局域网"),
        ("http://172.16.0.5", "lan", "局域网"),
        ("http://100.64.2.3", "tailscale", "Tailscale"),
        ("http://8.8.8.8", "public-http", "HTTPS"),
        ("http://qr.example.com", "public-http", "HTTPS"),
        ("https://qr.example.com", "public-https", "HTTPS"),
    ],
)
def test_network_classification(url, kind, text):
    result = classify_public_url(url)
    assert result.kind == kind
    assert text in result.message
