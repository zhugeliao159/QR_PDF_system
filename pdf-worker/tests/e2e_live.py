from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import fitz
import httpx
from PIL import Image


BASE_URL = os.getenv("E2E_BASE_URL", "http://127.0.0.1:18081").rstrip("/")
OUTPUT_DIR = Path(os.getenv("E2E_OUTPUT_DIR", "/work"))


def require(response: httpx.Response, status: int) -> dict:
    if response.status_code != status:
        raise RuntimeError(
            f"{response.request.method} {response.request.url}: "
            f"expected {status}, got {response.status_code}: {response.text}"
        )
    return response.json()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        require(client.get("/health"), 200)
        require(client.get("/capabilities"), 200)

        binding = require(
            client.post(
                "/bindings",
                files={"file": ("answer-v1.txt", b"answer version one", "text/plain")},
                data={"note": "stage 02 live verification"},
            ),
            201,
        )
        qr_id = binding["qr_id"]
        qr_url = binding["qr_url"]
        qr_response = client.get(f"/bindings/{qr_id}/qr.png")
        qr_response.raise_for_status()
        qr_path = OUTPUT_DIR / "qr.png"
        qr_path.write_bytes(qr_response.content)
        with Image.open(qr_path) as image:
            image.verify()

        source = fitz.open()
        for page_number in range(1, 3):
            page = source.new_page(width=595, height=842)
            page.insert_text((72, 72), f"Stage 02 exercise page {page_number}")
        source_bytes = source.tobytes()
        source.close()
        source_path = OUTPUT_DIR / "source.pdf"
        source_path.write_bytes(source_bytes)

        job = require(
            client.post(
                "/pdf/jobs",
                data={
                    "qr_id": qr_id,
                    "page": "1",
                    "position": "bottom-right",
                    "size_mm": "20",
                    "margin_mm": "10",
                },
                files={"file": ("exercise.pdf", source_bytes, "application/pdf")},
            ),
            201,
        )
        job_id = job["job_id"]
        output_response = client.get(f"/pdf/jobs/{job_id}/download")
        output_response.raise_for_status()
        output_path = OUTPUT_DIR / "output.pdf"
        output_path.write_bytes(output_response.content)
        if hashlib.sha256(output_response.content).hexdigest() != job["output_sha256"]:
            raise RuntimeError("downloaded output SHA-256 does not match job metadata")

        with fitz.open(output_path) as output_document:
            if output_document.page_count != 2:
                raise RuntimeError("output page count changed")
            target_page = output_document[0]
            if not target_page.get_images():
                raise RuntimeError("target page contains no QR image")
            pixmap = target_page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            pixmap.save(OUTPUT_DIR / "output-page-1.png")

        current_before = client.get(f"/r/{qr_id}")
        current_before.raise_for_status()
        if current_before.content != b"answer version one":
            raise RuntimeError("permanent URL did not return version one")

        replacement = require(
            client.put(
                f"/bindings/{qr_id}/file",
                files={"file": ("answer-v2.txt", b"answer version two", "text/plain")},
            ),
            200,
        )
        if replacement["qr_id"] != qr_id or replacement["qr_url"] != qr_url:
            raise RuntimeError("permanent QR identity changed after replacement")
        if client.get(f"/r/{qr_id}").content != b"answer version two":
            raise RuntimeError("permanent URL did not switch to version two")

        versions = require(client.get(f"/bindings/{qr_id}/versions"), 200)
        first_version = next(item for item in versions if item["version_number"] == 1)
        rolled_back = require(
            client.post(f"/bindings/{qr_id}/rollback/{first_version['version_id']}"),
            200,
        )
        if rolled_back["current_version"]["version_number"] != 1:
            raise RuntimeError("rollback did not select version one")
        if client.get(f"/r/{qr_id}").content != b"answer version one":
            raise RuntimeError("permanent URL did not return rolled-back content")

    print(
        json.dumps(
            {
                "status": "PASS",
                "qr_id": qr_id,
                "qr_url": qr_url,
                "job_id": job_id,
                "source_size_bytes": len(source_bytes),
                "source_pages": 2,
                "output_size_bytes": len(output_response.content),
                "output_sha256": job["output_sha256"],
                "versions": [item["version_number"] for item in versions],
                "current_version": 1,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
