from __future__ import annotations

import json
import os
import resource
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

from app.services.watermark import WatermarkService


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def sample_pages(root: Path) -> list[Path]:
    size = (1200, 1697)
    paths: list[Path] = []

    text = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(text)
    for y in range(60, 1600, 34):
        draw.text((70, y), f"Exercise analysis line {y // 34:02d}: reasoning and answer", fill="#202020")
    paths.append(root / "a4-text.webp")
    text.save(paths[-1], "WEBP", quality=82)

    formula = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(formula)
    for row, y in enumerate(range(45, 1640, 28)):
        draw.text((35, y), f"{row:02d}) integral(f(x)) dx = sum(a_i*x^i), x in [0, 1]", fill="#111111")
        for x in range(650, 1160, 55):
            draw.line((x, y + 4, x + 35, y + 20), fill="#333333", width=2)
    paths.append(root / "formula-dense.webp")
    formula.save(paths[-1], "WEBP", quality=82)

    color = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(color)
    for y in range(0, size[1], 80):
        for x in range(0, size[0], 80):
            draw.rectangle(
                (x, y, x + 79, y + 79),
                fill=((x * 3 + y) % 256, (x + y * 2) % 256, (x * 2 + y * 3) % 256),
            )
    paths.append(root / "color-page.webp")
    color.save(paths[-1], "WEBP", quality=82)
    return paths


def run_batch(service: WatermarkService, pages: list[Path], count: int, workers: int) -> dict:
    latencies: list[float] = []
    sizes: list[int] = []
    errors = 0
    cpu_start = time.process_time()
    wall_start = time.perf_counter()

    def render(index: int) -> tuple[float, int]:
        started = time.perf_counter()
        payload = service.render(pages[index % len(pages)], "QR-PERF-05C", f"V-P{index:07d}")
        return (time.perf_counter() - started) * 1000, len(payload)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(render, index) for index in range(count)]
        for future in as_completed(futures):
            try:
                latency, size = future.result()
                latencies.append(latency)
                sizes.append(size)
            except Exception:
                errors += 1
    return {
        "requests": count,
        "workers": workers,
        "p50_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(percentile(latencies, 0.95), 2),
        "wall_ms": round((time.perf_counter() - wall_start) * 1000, 2),
        "cpu_ms": round((time.process_time() - cpu_start) * 1000, 2),
        "mean_output_bytes": round(statistics.mean(sizes)) if sizes else 0,
        "errors": errors,
    }


def main() -> None:
    settings = SimpleNamespace(
        watermark_font_path=os.getenv("WATERMARK_FONT_PATH", ""),
        watermark_font_size=28,
        watermark_text_template="在线预览 | {material_code} | {trace_code} | {timestamp}",
        watermark_opacity=45,
        watermark_rotation_degrees=-25,
        watermark_spacing_x=420,
        watermark_spacing_y=280,
    )
    service = WatermarkService(settings)
    memory_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    with tempfile.TemporaryDirectory(prefix="stage05c-benchmark-") as directory:
        pages = sample_pages(Path(directory))
        singles = []
        for path in pages:
            started = time.perf_counter()
            payload = service.render(path, "QR-PERF-05C", "V-SINGLE05")
            singles.append({
                "page": path.stem,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "output_bytes": len(payload),
            })
        sequential = run_batch(service, pages, 20, 1)
        concurrent_5 = run_batch(service, pages, 20, 5)
        concurrent_10 = run_batch(service, pages, 20, 10)
    memory_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(json.dumps({
        "single_pages": singles,
        "batch_20": sequential,
        "concurrent_5": concurrent_5,
        "concurrent_10": concurrent_10,
        "max_rss_delta_kib": max(0, memory_after - memory_before),
        "watermark_font_mode": "chinese" if service.chinese_watermark_available else "ascii_fallback",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
