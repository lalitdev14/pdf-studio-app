# PDF Studio

An all-in-one PDF platform: React + TypeScript + Vite + Tailwind frontend, FastAPI (Python) backend.
Every operation runs for real on the server (no mock processing, no fake download links) and every result is a real, re-openable file.

```
backend/    FastAPI app (app/), services per tool (app/services/), tests (tests/)
frontend/   React SPA (src/pages, src/components, src/lib)
docker-compose.yml, backend/Dockerfile   one-container deployment (API + built SPA)
```

## Tools
Image → PDF · PDF → Image · PDF → Word/Excel/PowerPoint · Word/Excel/PowerPoint → PDF · Editor (text, text boxes, dates, highlight/underline/strike,
shapes, arrows, freehand, images, drawn signatures, comments, edit existing text, undo/redo, version history) · Merge · Split · Organize (visual,
drag & drop, undo/redo, insert pages from other PDFs) · Rotate · Add blank pages · Resize · Compress · Watermark · Remove (tagged) watermark ·
Page numbers · Headers/footers · OCR · Extract text · Extract images · Protect (AES-256) · Unlock (needs the password) · Digital signature (certificate) ·
Metadata · Flatten · Repair · Compare.  Optional accounts: history and saved files.

## Run it locally
Requirements: Python 3.11+, Node 20+, and system tools **poppler-utils** (pdftoppm/pdftotext/pdfimages), **tesseract-ocr** (OCR),
**LibreOffice** (Office → PDF). Missing tools do not break the rest: `/api/health` reports which features are available and the UI disables
the affected tools instead of pretending.

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env            # optional; export the variables or use your process manager
uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173, proxies /api to :8000
npm run typecheck               # optional strict type check
```

Optional extras: `pip install PyMuPDF` (true "edit existing text"; AGPL licence) and `pip install pyhanko` (certificate signatures).

## Docker
```bash
export SECRET_KEY=$(openssl rand -hex 32)
docker compose up --build       # http://localhost:8000
```

## Configuration (environment variables)
See `backend/.env.example` for all of them. The important ones: `SECRET_KEY`, `DATA_DIR`, `MAX_FILE_MB`, `MAX_REQUEST_MB`, `FILE_TTL_MINUTES`,
`CORS_ORIGINS`, `RATE_LIMIT_*`, `MAX_PAGES`, `FRONTEND_DIST`, `TRUST_PROXY`.
For production put it behind HTTPS (reverse proxy), set `TRUST_PROXY=true` only if the proxy sets `X-Forwarded-For`, and use a persistent volume for `DATA_DIR`.

## API overview
`GET /api/health` · `POST /api/files` (multipart upload) · `GET /api/files/{id}/info|download|pages/{n}/thumbnail|text-lines` · `DELETE /api/files/{id}` ·
`POST /api/convert/*` and `POST /api/pdf/*` (JSON `{file_ids, options}` or multipart) return a **job**; poll `GET /api/jobs/{id}`, cancel with
`POST /api/jobs/{id}/cancel`, ZIP with `GET /api/jobs/{id}/zip`. Auth: `/api/auth/*`, `/api/me/*`. Interactive docs at `/api/docs`.

## Security and privacy design
Files are validated by content (magic bytes), size- and page-limited, stored under random ids, served only through signed expiring URLs,
and deleted after `FILE_TTL_MINUTES` (or immediately via "Delete files now"). Rate limiting, request-size guard, CSP/security headers,
scrypt password hashing, signed auth tokens, subprocess timeouts, isolated LibreOffice profile. Errors never leak internal paths.
**Passwords are never bypassed**: Unlock/Protect/Compress/etc. only open encrypted PDFs when you supply the correct password; "Remove watermark"
only removes watermarks tagged as such in the PDF structure and says so otherwise.

## Tests
`cd backend && pytest` → 71 tests (services, API flow, storage/jobs/auth/security helpers). Slow tests needing LibreOffice are marked `slow`.

## What was and was not verified (please read)
Built and tested in a sandbox without network access, so:
- **Verified:** all backend services and the HTTP layer (through a custom ASGI client against the same handlers) – 71 passing tests, outputs re-opened and rendered.
- **Not verified:** the **frontend has never been built or run** (no npm registry access here). It passed a TypeScript syntax check and an import/export
  check only. Expect to fix small type or runtime errors on first `npm run dev`/`npm run typecheck`. `npm run build` deliberately skips type-checking so a stray
  type error does not block a build.
- **Not verified:** the real FastAPI/uvicorn wiring (FastAPI was not installable here), PyMuPDF text replacement, pyHanko signing, HEIC input, Docker build,
  OCR and Office conversions beyond what the sandbox had installed.

## Known limitations
- PDF → Word/Excel/PowerPoint are best-effort *reconstructions* from text/tables/layout, not pixel-perfect conversions; scanned PDFs need OCR first.
- Editor "Add text" etc. draw on top of the page; only "Edit existing text" (PyMuPDF) truly removes original text, and it needs unrotated pages and Latin-1 text.
- Remove watermark works only for tagged watermarks (such as those added by this app).
- Password reset has no mail server: tokens are only returned when `EXPOSE_RESET_TOKEN=true` (development). Wire up SMTP for production.
- Jobs, rate limits and sessions live in one process's memory/SQLite: run a single worker process, or move them to Redis/Postgres to scale out.
- Cloud-storage import (Drive/Dropbox) and AI features (summaries, chat) from the wish-list are **not implemented**.
- No automated frontend tests; accessibility was considered (labels, focus rings, keyboard undo/delete) but not audited.
