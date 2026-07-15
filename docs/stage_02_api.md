# Stage 02 API

Base URL in the current SSH-tunnel environment: `http://127.0.0.1:18081`.
Interactive OpenAPI documentation is available at `/docs`. Upload endpoints use
`multipart/form-data`. Errors use this envelope:

```json
{"error":{"code":"ERROR_CODE","message":"description","details":{}}}
```

Internal filesystem paths and tracebacks are never included in API errors.

## Bindings

### `POST /bindings`

Fields: required `file`, optional `note`. Creates a random 128-bit UUID4-based
`qr_id`, version 1, `qr_url`, and `qr_png_url`. Returns `201`.

### `GET /bindings/{qr_id}`

Returns binding metadata, the current version, version count, SHA-256, timestamps,
and stable URLs. Missing and inactive bindings return `404` and `410`.

### `GET /bindings/{qr_id}/qr.png`

Returns a black-on-white PNG encoding `{PUBLIC_BASE_URL}/r/{qr_id}` with QR error
correction level Q and a four-module quiet zone.

### `PUT /bindings/{qr_id}/file`

Fields: required `file`, optional `note`. Saves an independent version, atomically
switches the current version, and retains at most the newest five versions. The
`qr_id`, `qr_url`, and QR image content do not change.

### `GET /bindings/{qr_id}/versions`

Returns versions newest first. Each item includes `version_id`, monotonically
increasing `version_number`, filename, MIME type, size, SHA-256, timestamp,
optional note, and `is_current`.

### `POST /bindings/{qr_id}/rollback/{version_id}`

Selects an existing version belonging to the binding without copying or deleting
other versions. A version from another binding returns `VERSION_NOT_FOUND`.

### `GET /r/{qr_id}`

Returns the current file with `no-cache, no-store, must-revalidate`. PDFs and
images use inline content disposition; other files download as attachments.
Replacement and rollback change the returned file without changing this URL.

## PDF jobs

### `POST /pdf/jobs`

Fields:

| Field | Required | Rules |
| --- | --- | --- |
| `file` | yes | `.pdf`, PDF MIME, valid and unencrypted |
| `qr_id` | yes | Active existing binding |
| `page` | no | 1-based, default `1` |
| `position` | no | `top-left`, `top-right`, `bottom-left`, `bottom-right` |
| `size_mm` | no | `10..50`, default from environment |
| `margin_mm` | no | `0..50`, default from environment |

The synchronous operation creates a persistent job, saves the source PDF, stamps
the permanent QR on the selected page, verifies that the output reopens with the
same page count, records size/SHA-256, and atomically publishes the result. It
returns `201` with status `completed`. Processing failures remain queryable as
status `failed`; their error response includes `details.job_id` when a job record
was created.

### `GET /pdf/jobs/{job_id}`

Returns status, parameters, timestamps, output metadata/download URL, or the
stored error code and message.

### `GET /pdf/jobs/{job_id}/download`

Downloads completed output as PDF with `Cache-Control: no-store`. Failed or
incomplete jobs return `409 PDF_JOB_NOT_COMPLETED`.

## Limits and common errors

- Uploads are streamed in 1 MiB chunks and capped by `MAX_UPLOAD_SIZE_MB`; excess
  data returns `413 UPLOAD_TOO_LARGE` and the temporary file is removed.
- Empty uploads return `400 EMPTY_FILE`.
- Damaged, disguised, encrypted, or over-page-limit PDFs return a specific `4xx`.
- Invalid page, position, size, margin, or a QR that cannot fit returns `422`.
- Missing stored data returns a controlled `409`, never an internal path.
- The application permits PDF and image binding files and generic attachment
  files; PDF job uploads are intentionally stricter.

## Health

`GET /health` verifies runtime dependencies, configured paths, SQLite read/write,
and storage write access. `GET /capabilities` reports the same capabilities and
non-secret limits. Either returns `503` when a required capability is unavailable.
