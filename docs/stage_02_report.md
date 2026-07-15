# Stage 02 Implementation and Verification Report

Verification date: 2026-07-15 (Asia/Shanghai). Result: **PASS**.

## Delivered scope

- Persistent SQLite schema version 1 with `bindings`, `file_versions`, and
  `pdf_jobs`; foreign keys and a 5-second busy timeout are enabled per connection.
- Local storage abstraction with streamed uploads, application size enforcement,
  SHA-256, generated storage names, root confinement, symlink rejection, fsync,
  temporary files, and atomic rename.
- Permanent `/r/{qr_id}` entry and deterministic QR PNG using configurable
  `PUBLIC_BASE_URL`.
- Atomic replacement, newest-five cleanup, history query, and rollback.
- Synchronous persistent PDF jobs for a selected 1-based page and four preset
  corners, with configurable size/margin, output reopen/page-count verification,
  SHA-256, and download.
- Uniform public error envelopes, expanded health/capabilities, isolated test
  image, persistent Compose mounts, and updated operations documentation.

QuickDrop source, database, and files were not edited by the implementation. A
pre-change source backup was created at
`/home/user/projects/qr-exercise-prototype-stage01-20260715T021900Z.tar.gz`
(SHA-256 `c334c10f9af9e203e9659892282a39a2b8e62edae7ae27a6add0c43fa73a17ca`).

## Automated verification

Command:

```bash
docker compose --profile test build pdf-worker-tests
docker compose --profile test run --rm pdf-worker-tests
```

Result: `29 passed, 0 failed, 0 skipped` in 2.85 seconds. Five non-failing
PyMuPDF/SWIG deprecation warnings were emitted. Coverage includes health and
error envelopes, permanent files and QR PNG, stable identity during replacement,
failed replacement safety, newest-five cleanup and physical file removal,
rollback and cross-binding rejection, process-level persistence, all four PDF
corners, selected/rotated pages, output hash/page count, invalid parameters,
damaged/disguised/encrypted PDFs, empty uploads, the 1 MiB test upload limit, and
the configured page limit, path traversal, and symbolic-link rejection.

`python -m compileall -q pdf-worker/app pdf-worker/tests` and
`docker compose config --quiet` also passed.

## Live E2E verification

The live helper called the deployed service over `127.0.0.1:18081`; it did not
call service classes directly. It created:

- `qr_id`: `6e69e5d0204542b39d19493a4f64cdea`
- stable URL: `http://127.0.0.1:18081/r/6e69e5d0204542b39d19493a4f64cdea`
- `job_id`: `2a4953db77b5437594cb00b4a564d883`
- source PDF: 1,161 bytes, 2 pages
- output PDF: 12,376 bytes, 2 pages
- output SHA-256: `06a01a1409b6b7ef4f86984d33024ae445c889b7b655134c4a181acd8131f51b`

The test opened the QR PNG with Pillow, opened the output PDF with PyMuPDF,
confirmed unchanged page count and an image on page 1, downloaded and hash-checked
the output, replaced version 1 with version 2 without changing `qr_id/qr_url`,
confirmed `/r/` returned version 2, listed versions `[2, 1]`, rolled back to
version 1, and confirmed `/r/` returned version 1 again.

Page 1 was rendered at 1.5x and manually inspected. The 20 mm QR was clear in the
bottom-right preset, had the requested 10 mm page margin and QR quiet zone, and
was neither clipped nor outside the page. Artifacts were copied to the Windows
workspace as `qr.png`, `output.pdf`, and `output-page-1.png`.

## Restart and persistence

After `docker compose restart pdf-worker`, the same binding, permanent entry,
job query, and job download all returned HTTP 200. The downloaded SHA-256 still
matched `06a01a...1f51b`.

After `docker compose down` followed by `docker compose up -d`, those same four
checks again returned HTTP 200 and the download hash remained unchanged. Both
containers returned to healthy state. QuickDrop legitimately touched its own
SQLite files during normal shutdown/startup; no direct SQL or file edit was made
by this work. Its existing uploaded file remained present and QuickDrop returned
HTTP 302 at `/`, its expected login redirect.

## Runtime and security verification

- QuickDrop: healthy, `127.0.0.1:18080`, approximately 340.2 MiB at measurement.
- PDF Worker: healthy, `/health` 200, `/capabilities` 200.
- PDF Worker limits: 1 CPU, 512 MiB, 128 PIDs; approximately 50.76 MiB and 3 PIDs.
- PDF Worker user: non-root `appuser`.
- Port publish: only `127.0.0.1:18081 -> 8000`.
- Security: `no-new-privileges:true`, `cap_drop: ALL`.
- Logging: Docker `json-file`, `max-size=10m`, `max-file=3`.
- Persistent disk at measurement: database 60 KiB, business storage 52 KiB.

The container listens on `0.0.0.0:8000` only inside its private network namespace;
the host publish is explicitly loopback-only.

## Known limitations

There is no application authentication, so loopback publishing and SSH access
remain mandatory. A phone cannot use a QR containing `127.0.0.1`, because that
address points back to the phone. Batch operations, multiple QR stamps, arbitrary
coordinates, users/roles, scan analytics, public HTTPS, queues, external databases,
and production backup automation are not implemented.
