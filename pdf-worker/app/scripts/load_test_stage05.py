from __future__ import annotations

import argparse
import http.cookiejar
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Sample:
    status: int
    latency_ms: float
    endpoint: str


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


class SessionClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def get(self, path: str) -> tuple[Sample, bytes]:
        started = time.perf_counter()
        try:
            with self.opener.open(self.base_url + path, timeout=30) as response:
                content = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            content = error.read()
            status = error.code
        except Exception:
            return Sample(599, (time.perf_counter() - started) * 1000, path), b""
        return Sample(status, (time.perf_counter() - started) * 1000, path), content


def run_session(base_url: str, token: str, pages_per_session: int) -> list[Sample]:
    client = SessionClient(base_url)
    samples: list[Sample] = []
    entry, _ = client.get(f"/q/{token}")
    samples.append(entry)
    manifest, content = client.get(f"/q/{token}/manifest")
    samples.append(manifest)
    if entry.status != 200 or manifest.status != 200:
        return samples
    try:
        page_count = max(1, int(json.loads(content)["page_count"]))
    except Exception:
        return samples + [Sample(598, 0.0, "manifest_parse")]
    for index in range(pages_per_session):
        page_number = (index % page_count) + 1
        sample, _ = client.get(f"/q/{token}/pages/{page_number}")
        samples.append(sample)
    return samples


def run_scenario(base_url: str, token: str, sessions: int, pages: int) -> dict[str, Any]:
    samples: list[Sample] = []
    wall_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=sessions) as executor:
        futures = [executor.submit(run_session, base_url, token, pages) for _ in range(sessions)]
        for future in as_completed(futures):
            samples.extend(future.result())
    latencies = [sample.latency_ms for sample in samples]
    successes = sum(1 for sample in samples if 200 <= sample.status < 400)
    return {
        "concurrent_sessions": sessions,
        "pages_per_session": pages,
        "requests": len(samples),
        "successes": successes,
        "success_rate": round(successes / len(samples), 4) if samples else 0,
        "status_429": sum(sample.status == 429 for sample in samples),
        "status_5xx": sum(500 <= sample.status < 600 for sample in samples),
        "transport_errors": sum(sample.status in {598, 599} for sample in samples),
        "p50_ms": round(statistics.median(latencies), 2) if latencies else 0,
        "p95_ms": round(percentile(latencies, 0.95), 2),
        "p99_ms": round(percentile(latencies, 0.99), 2),
        "wall_ms": round((time.perf_counter() - wall_started) * 1000, 2),
    }


def rate_limit_probe(base_url: str, token: str, requests: int) -> dict[str, Any]:
    client = SessionClient(base_url)
    entry, _ = client.get(f"/q/{token}")
    statuses: list[int] = [entry.status]
    for _ in range(requests):
        sample, _ = client.get(f"/q/{token}/pages/1")
        statuses.append(sample.status)
    return {
        "requests": len(statuses),
        "status_200": statuses.count(200),
        "status_429": statuses.count(429),
        "status_5xx": sum(500 <= value < 600 for value in statuses),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 05D 轻量 Viewer Session 压力测试")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--sessions", default="20,50")
    parser.add_argument("--pages-per-session", type=int, default=10)
    parser.add_argument("--rate-probe", type=int, default=125)
    args = parser.parse_args()
    scenarios = []
    for raw in args.sessions.split(","):
        count = int(raw)
        if count < 1 or count > 100:
            raise SystemExit("并发 Session 必须在 1 到 100 之间")
        scenarios.append(
            run_scenario(args.base_url, args.token, count, args.pages_per_session)
        )
    result = {
        "scenarios": scenarios,
        "rate_limit_probe": rate_limit_probe(
            args.base_url, args.token, args.rate_probe
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    unexpected = sum(item["status_5xx"] + item["transport_errors"] for item in scenarios)
    unexpected += result["rate_limit_probe"]["status_5xx"]
    return 1 if unexpected else 0


if __name__ == "__main__":
    raise SystemExit(main())
