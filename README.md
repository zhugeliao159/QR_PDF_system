# QR Exercise Prototype

This internal prototype runs QuickDrop and a PDF Worker. Stage 02 adds permanent
QR identifiers, five-version file bindings, rollback, and single-QR PDF stamping.
Both services remain bound to the server loopback interface and are intended to
be reached from Windows through an SSH tunnel.

## Services and data

- QuickDrop: `http://127.0.0.1:18080`
- PDF Worker and OpenAPI: `http://127.0.0.1:18081/docs`
- PDF Worker database: `data/pdf-worker/db/app.db`
- Bound files: `data/pdf-worker/storage/bindings/`
- Uploaded source PDFs: `data/pdf-worker/storage/source-pdfs/`
- Generated PDFs: `data/pdf-worker/storage/generated-pdfs/`
- Legacy worker paths: `data/pdf-worker/{input,output}/`

All `data/` content and `.env` are excluded from Git. The PDF Worker owns its
business database and storage. It does not read or edit the QuickDrop database.

## Configuration

Copy values from `.env.example` into `.env` and adjust them before starting.

| Variable | Default | Purpose |
| --- | --- | --- |
| `QUICKDROP_PORT` | `18080` | Loopback QuickDrop port |
| `PDF_WORKER_PORT` | `18081` | Loopback PDF Worker port |
| `TZ` | `Asia/Shanghai` | Container timezone |
| `PUBLIC_BASE_URL` | `http://127.0.0.1:18081` | Base embedded in QR codes and returned URLs |
| `MAX_UPLOAD_SIZE_MB` | `100` | Application-enforced upload limit |
| `MAX_PDF_PAGES` | `500` | PDF page limit |
| `MAX_BINDING_VERSIONS` | `5` | Versions retained per permanent ID |
| `DEFAULT_QR_SIZE_MM` | `20` | Default printed QR size |
| `DEFAULT_QR_MARGIN_MM` | `10` | Default page-edge margin |
| `PDF_WORKER_DATABASE_PATH` | `/data/db/app.db` | Container database path |
| `PDF_WORKER_STORAGE_ROOT` | `/data/storage` | Container business storage root |

`PUBLIC_BASE_URL=http://127.0.0.1:18081` works from the Windows computer that
owns the SSH tunnel. A phone scanning the printed QR code resolves `127.0.0.1`
to the phone itself, so it cannot reach this server. Keep the setting configurable;
use a reachable LAN, Tailscale, or HTTPS domain only in a later deployment with
the corresponding network and security design.

## Start and update

```bash
cd ~/projects/qr-exercise-prototype
docker compose config
docker compose build pdf-worker
docker compose up -d
docker compose ps
curl -fsS http://127.0.0.1:18081/health
curl -fsS http://127.0.0.1:18081/capabilities
```

The database schema initializes idempotently on startup. Existing data is not
deleted during an update. Stop without deleting volumes or bind-mounted data:

```bash
docker compose down
```

Never use `docker compose down -v` or delete `data/` for a normal update.

## Windows access

Keep this PowerShell session open:

```powershell
ssh -L 18080:127.0.0.1:18080 -L 18081:127.0.0.1:18081 tx
```

Open QuickDrop at `http://127.0.0.1:18080` and the PDF Worker API at
`http://127.0.0.1:18081/docs`.

## Core workflow

Create a binding:

```bash
curl -F "file=@answer.pdf;type=application/pdf" \
  -F "note=chapter 1" http://127.0.0.1:18081/bindings
```

Use the returned `qr_id` in the following examples:

```bash
curl -o qr.png http://127.0.0.1:18081/bindings/QR_ID/qr.png
curl -OJ http://127.0.0.1:18081/r/QR_ID

curl -X PUT -F "file=@answer-v2.pdf;type=application/pdf" \
  http://127.0.0.1:18081/bindings/QR_ID/file

curl http://127.0.0.1:18081/bindings/QR_ID/versions
curl -X POST http://127.0.0.1:18081/bindings/QR_ID/rollback/VERSION_ID

curl -F "file=@exercise.pdf;type=application/pdf" \
  -F "qr_id=QR_ID" -F "page=1" -F "position=bottom-right" \
  -F "size_mm=20" -F "margin_mm=10" \
  http://127.0.0.1:18081/pdf/jobs

curl -OJ http://127.0.0.1:18081/pdf/jobs/JOB_ID/download
```

See `docs/stage_02_api.md` for response fields and error behavior.

## Tests

The test profile has no production data mounts and exposes no host ports:

```bash
docker compose --profile test build pdf-worker-tests
docker compose --profile test run --rm pdf-worker-tests
```

Stage 02 verification produced `29 passed`. The live E2E helper is intentionally
separate because it creates records in the running PDF Worker:

```bash
docker run --rm --network host -v /tmp/stage2-e2e:/work \
  qr-exercise-prototype-pdf-worker-tests:local python tests/e2e_live.py
```

## Backup

Stop services for a consistent file-level backup:

```bash
cd ~/projects/qr-exercise-prototype
docker compose down
tar -czf ../qr-exercise-data-$(date +%F).tar.gz data/
docker compose up -d
```

## Security boundary

The prototype has no user authentication or authorization. It relies on
loopback-only publishing and SSH access. The PDF Worker runs as a non-root user,
drops all Linux capabilities, enables `no-new-privileges`, limits CPU, memory,
and PIDs, and rotates Docker logs. Uploaded names are display metadata only;
storage names are generated and resolved within the configured root.

## Not implemented

Batch upload/stamping/export, multiple QR codes per PDF, PDF merge, arbitrary
coordinates or drag-and-drop placement, users and roles, scan analytics, public
domain and HTTPS, Redis/Celery/queues, external databases, Kubernetes, and a
production backup/restore system remain outside Stage 02.
