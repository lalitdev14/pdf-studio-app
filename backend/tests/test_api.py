"""End-to-end tests of the HTTP layer: upload, validation, jobs, downloads, auth, limits."""
from __future__ import annotations

import io
import json
import os
import time
import zipfile

import pikepdf
import pytest
from PIL import Image

from asgi_client import Client, build_app
from conftest import make_image, make_pdf

ENV_DEFAULTS = {
    "MAX_FILE_MB": "100", "MAX_REQUEST_MB": "300", "RATE_LIMIT_MUTATING_PER_MIN": "100000",
    "RATE_LIMIT_READ_PER_MIN": "100000", "FILE_TTL_MINUTES": "60", "EXPOSE_RESET_TOKEN": "0",
}


@pytest.fixture()
def api(monkeypatch):
    for k, v in ENV_DEFAULTS.items():
        monkeypatch.setenv(k, v)
    app = build_app()
    yield Client(app)
    from app.state import reset_services

    reset_services()


def pdf_bytes(tmp, pages=3, label="Doc") -> bytes:
    return make_pdf(tmp / f"{label}.pdf", pages, label=label).read_bytes()


def download(c: Client, out: dict) -> bytes:
    r = c.get(out["url"])
    assert r.status == 200, r.body
    return r.body


def test_health_and_security_headers(api):
    r = api.get("/api/health")
    assert r.status == 200
    body = r.json()
    assert body["status"] == "ok" and body["limits"]["max_file_mb"] == 100
    assert set(body["features"]) >= {"ocr", "office", "replace_text", "digital_signature", "heic"}
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY" and r.headers["cache-control"] == "no-store"


def test_cors_preflight(api):
    r = api.request("OPTIONS", "/api/pdf/merge", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    r = api.request("OPTIONS", "/api/pdf/merge", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


def test_upload_info_thumbnail_text_lines(api, tmp):
    f = api.upload("My report (final).pdf", pdf_bytes(tmp, 2, "Info"))
    assert f["kind"] == "pdf" and f["name"] == "My report (final).pdf"
    info = api.get(f"/api/files/{f['id']}/info").json()
    assert info["pages"] == 2 and info["security"]["encrypted"] is False
    th = api.get(f"/api/files/{f['id']}/pages/1/thumbnail?width=180")
    assert th.status == 200 and th.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(th.body)).size[0] == 180
    assert api.get(f"/api/files/{f['id']}/pages/9/thumbnail").status == 404
    tl = api.get(f"/api/files/{f['id']}/pages/1/text-lines").json()
    assert tl["lines"][0]["text"].startswith("Info 1 of 2")


def test_merge_via_multipart_then_chain_with_file_ids(api, tmp):
    a, b = pdf_bytes(tmp, 2, "AAA"), pdf_bytes(tmp, 3, "BBB")
    job = api.run("/api/pdf/merge", files=[("a.pdf", a), ("b.pdf", b)], options={"pages": ["", "1-2"]})
    assert job["status"] == "done" and job["progress"] == 100 and job["error"] is None
    out = job["outputs"][0]
    assert out["name"] == "merged.pdf" and out["mime"] == "application/pdf"
    merged = download(api, out)
    with pikepdf.open(io.BytesIO(merged)) as pdf:
        assert len(pdf.pages) == 4
    # workspace flow: feed the output of one tool into the next without re-uploading
    job2 = api.run("/api/pdf/rotate", ids=[out["id"]], options={"angle": 90, "pages": "1"})
    job3 = api.run("/api/pdf/page-numbers", ids=[job2["outputs"][0]["id"]], options={"format": "{n}"})
    final = download(api, job3["outputs"][0])
    from pypdf import PdfReader
    from app.services.common import displayed_size

    pages = PdfReader(io.BytesIO(final)).pages
    assert len(pages) == 4
    w0, h0 = displayed_size(pages[0])
    w1, h1 = displayed_size(pages[1])
    assert w0 > h0 and w1 < h1  # page 1 still shows rotated; page numbers did not undo it
    assert api.get(f"/api/files/{out['id']}/info").status == 200  # earlier versions stay available


def test_split_zip_download(api, tmp):
    job = api.run("/api/pdf/split", files=[("doc.pdf", pdf_bytes(tmp, 4))], options={"mode": "every"})
    assert len(job["outputs"]) == 4
    z = api.get(f"/api/jobs/{job['id']}/zip")
    assert z.status == 200 and z.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(z.body)) as zf:
        assert sorted(zf.namelist()) == [f"doc_page_0{i}.pdf" for i in range(1, 5)]
        for n in zf.namelist():
            with pikepdf.open(io.BytesIO(zf.read(n))) as pdf:
                assert len(pdf.pages) == 1
    assert api.get("/api/jobs/" + "x" * 30 + "/zip").status == 404


def test_image_to_pdf_endpoint(api, tmp):
    imgs = [(f"{i}.png", make_image(tmp / f"{i}.png", fmt="PNG").read_bytes()) for i in range(3)]
    job = api.run("/api/convert/image-to-pdf", files=imgs, options={"page_size": "a5", "rotations": [0, 90, 0]})
    assert job["status"] == "done" and job["meta"]["pages"] == 3
    with pikepdf.open(io.BytesIO(download(api, job["outputs"][0]))) as pdf:
        assert len(pdf.pages) == 3


def test_pdf_to_image_and_all_outputs_zip(api, tmp):
    job = api.run("/api/convert/pdf-to-image", files=[("d.pdf", pdf_bytes(tmp, 3))], options={"dpi": 50, "format": "jpg"})
    assert [o["name"] for o in job["outputs"]] == [f"d-page-00{i}.jpg" for i in (1, 2, 3)]
    assert Image.open(io.BytesIO(download(api, job["outputs"][1]))).format == "JPEG"


# ------------------------------------------------------------------ validation
def test_file_signature_validation(api):
    exe = b"MZ\x90\x00" + b"\x00" * 200
    r = api.post("/api/files", files=[("files", "invoice.pdf", exe)])
    assert r.status == 415 and r.error["code"] == "unsupported_format"
    r = api.post("/api/files", files=[("files", "empty.pdf", b"")])
    assert r.status == 422 and r.error["code"] == "empty_file"
    r = api.post("/api/files", files=[("files", "page.html", b"<script>alert(1)</script>")])
    assert r.status == 415
    r = api.post("/api/files", files=[("files", "../../etc/passwd.pdf", b"%PDF-1.4\n")])
    assert r.status == 201 and r.json()["files"][0]["name"] == "passwd.pdf"
    r = api.post("/api/files", fields={"x": "1"})
    assert r.status == 422 and r.error["code"] == "no_files"
    r = api.post("/api/files", json={"a": 1})
    assert r.status == 422 and r.error["code"] == "invalid_content_type"


def test_wrong_file_type_and_count_for_tool(api, tmp):
    from app.state import get_services

    store_root = get_services().store.root
    before = len(list(store_root.iterdir()))
    img = make_image(tmp / "a.png", fmt="PNG").read_bytes()
    r = api.post("/api/pdf/merge", files=[("files", "a.png", img), ("files", "b.png", img)], fields={"options": "{}"})
    assert r.status == 415 and "PDF" in r.error["message"]
    pdf = pdf_bytes(tmp, 1)
    r = api.post("/api/pdf/merge", files=[("files", "a.pdf", pdf)], fields={"options": "{}"})
    assert r.status == 422 and r.error["code"] == "wrong_file_count"
    r = api.post("/api/convert/image-to-pdf", files=[("files", "a.pdf", pdf)], fields={"options": "{}"})
    assert r.status == 415
    assert len(list(store_root.iterdir())) == before, "rejected uploads must not linger in the store"


def test_invalid_options_have_readable_messages(api, tmp):
    pdf = pdf_bytes(tmp, 2)
    r = api.post("/api/pdf/compress", files=[("files", "a.pdf", pdf)], fields={"options": json.dumps({"level": "extreme"})})
    assert r.status == 422 and r.error["code"] == "invalid_options" and "level" in r.error["message"]
    r = api.post("/api/pdf/protect", files=[("files", "a.pdf", pdf)], fields={"options": json.dumps({"user_password": "x", "allow_copy": False})})
    assert r.status == 422 and "owner password" in r.error["message"]
    r = api.post("/api/pdf/rotate", files=[("files", "a.pdf", pdf)], fields={"options": "{not json"})
    assert r.status == 422 and r.error["code"] == "invalid_request"
    r = api.post("/api/pdf/unlock", files=[("files", "a.pdf", pdf)], fields={"options": "{}"})
    assert r.status == 422 and "authorised" in r.error["message"]


def test_file_size_limit(monkeypatch, tmp):
    for k, v in ENV_DEFAULTS.items():
        monkeypatch.setenv(k, v)
    c = Client(build_app(MAX_FILE_MB=1))
    big = b"%PDF-1.4\n" + b"0" * (1_100_000)
    r = c.post("/api/files", files=[("files", "big.pdf", big)])
    assert r.status == 413 and "1 MB" in r.error["message"]
    assert c.post("/api/files", files=[("files", "ok.pdf", pdf_bytes(tmp, 1))]).status == 201
    # Content-Length guard fires before the body is read
    c2 = Client(build_app(MAX_FILE_MB=1, MAX_REQUEST_MB=1))
    r = c2.post("/api/files", files=[("files", "x.pdf", b"%PDF" + b"0" * 3_000_000)])
    assert r.status == 413 and r.error["code"] == "too_large"


def test_unknown_and_malformed_ids(api):
    assert api.get("/api/files/" + "A" * 32 + "/info").status == 404
    assert api.get("/api/files/short/info").status == 404
    r = api.post("/api/pdf/rotate", json={"file_ids": ["nope"], "options": {}})
    assert r.status == 404 and r.error["code"] == "file_not_found"
    assert api.get("/api/jobs/" + "z" * 32).status == 404


# ------------------------------------------------- failure reporting and secrets
def test_corrupt_pdf_fails_the_job_with_a_clear_error(api):
    bad = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF"
    job = api.run("/api/pdf/rotate", files=[("bad.pdf", bad)], options={"angle": 90})
    assert job["status"] == "failed" and job["outputs"] == []
    assert job["error"]["code"] in ("corrupt_file", "corrupt_pdf")
    assert "Repair" in job["error"]["message"]


def test_password_protected_flow_and_password_not_leaked(api, tmp):
    f = api.run("/api/pdf/protect", files=[("d.pdf", pdf_bytes(tmp, 2))],
                options={"user_password": "s3cret-pw", "owner_password": "own3r-pw"})
    enc_id = f["outputs"][0]["id"]
    info = api.get(f"/api/files/{enc_id}/info").json()
    assert info["security"] == {"encrypted": True, "needs_password": True} and info["pages"] is None
    job = api.run("/api/pdf/rotate", ids=[enc_id], options={"angle": 90})
    assert job["status"] == "failed" and job["error"]["code"] == "password_required"
    job = api.run("/api/pdf/rotate", ids=[enc_id], options={"angle": 90, "password": "wrong"})
    assert job["error"]["code"] == "wrong_password"
    job = api.run("/api/pdf/rotate", ids=[enc_id], options={"angle": 90, "password": "s3cret-pw"})
    assert job["status"] == "done"
    assert "s3cret-pw" not in json.dumps(job) and "own3r-pw" not in json.dumps(job)
    un = api.run("/api/pdf/unlock", ids=[enc_id], options={"password": "s3cret-pw", "confirm_authorized": True})
    with pikepdf.open(io.BytesIO(download(api, un["outputs"][0]))) as pdf:
        assert not pdf.is_encrypted


def test_unexpected_errors_do_not_leak_internals(api, tmp, monkeypatch):
    from app.services import OPERATIONS

    def boom(ctx):
        raise RuntimeError("secret internal path /srv/x")

    spec = OPERATIONS["rotate"]
    monkeypatch.setitem(OPERATIONS, "rotate", type(spec)(**{**spec.__dict__, "func": boom}))
    app = build_app()
    c = Client(app)
    job = c.run("/api/pdf/rotate", files=[("a.pdf", pdf_bytes(tmp, 1))], options={})
    assert job["status"] == "failed" and job["error"]["code"] == "internal_error"
    assert "secret" not in json.dumps(job)


# ------------------------------------------------------------ links and expiry
def test_download_links_are_signed_and_expire(api, tmp):
    from app.signing import sign_download
    from app.state import get_services

    f = api.upload("a.pdf", pdf_bytes(tmp, 1))
    assert api.get(f["url"]).status == 200
    bare = f["url"].split("?")[0]
    assert api.get(bare).status == 403
    exp, sig = f["url"].split("exp=")[1].split("&sig=")
    assert api.get(f"{bare}?exp={exp}&sig={sig[:-2]}xx").status == 403
    other = api.upload("b.pdf", pdf_bytes(tmp, 1))
    assert api.get(f"/api/files/{other['id']}/download?exp={exp}&sig={sig}").status == 403  # sig bound to the file
    secret = get_services().settings.secret_key
    e2, s2 = sign_download(secret, f["id"], -5)
    assert api.get(f"{bare}?exp={e2}&sig={s2}").status == 403
    inline = api.get(f["url"] + "&inline=1")
    assert inline.headers["content-disposition"].startswith("inline")
    assert api.get(f["url"]).headers["content-disposition"].startswith("attachment")


def test_delete_and_expiry_sweep(api, tmp):
    from app.state import get_services

    f = api.upload("a.pdf", pdf_bytes(tmp, 1))
    assert api.delete(f["url"].replace("/download", "")).status == 200
    assert api.get(f"/api/files/{f['id']}/info").status == 404
    g = api.upload("b.pdf", pdf_bytes(tmp, 1))
    svc = get_services()
    assert svc.store.sweep(now=time.time() + 10) == 0
    assert svc.store.sweep(now=time.time() + svc.settings.file_ttl_seconds + 5) >= 1
    assert api.get(f"/api/files/{g['id']}/info").status == 404
    assert api.get(g["url"]).status == 404


# ------------------------------------------------------- jobs: cancel / dedupe
@pytest.fixture()
def slow_api(monkeypatch):
    for k, v in ENV_DEFAULTS.items():
        monkeypatch.setenv(k, v)
    from app.schemas import NoOptions
    from app.services import OPERATIONS, OpSpec

    def slow(ctx):
        for i in range(400):
            ctx.check_cancel()
            ctx.progress(i / 4, "working")
            time.sleep(0.025)
        out = ctx.new_path(".pdf")
        out.write_bytes(ctx.inputs[0].path.read_bytes())
        ctx.add_output(out, "slow.pdf")

    monkeypatch.setitem(OPERATIONS, "slow", OpSpec("slow", "/api/test/slow", slow, NoOptions))
    yield Client(build_app())
    from app.state import reset_services

    reset_services()


def test_progress_cancel_and_duplicate_submission(slow_api, tmp):
    c = slow_api
    f = c.upload("a.pdf", pdf_bytes(tmp, 1))
    j1 = c.run("/api/test/slow", ids=[f["id"]], wait=False)
    j2 = c.run("/api/test/slow", ids=[f["id"]], wait=False)
    assert j1["id"] == j2["id"], "identical in-flight request must not be processed twice"
    time.sleep(0.4)
    running = c.get(f"/api/jobs/{j1['id']}").json()
    assert running["status"] == "running" and 0 < running["progress"] < 100 and running["message"] == "working"
    t0 = time.time()
    assert c.post(f"/api/jobs/{j1['id']}/cancel").status == 200
    done = c.wait(j1["id"])
    assert done["status"] == "cancelled" and done["outputs"] == [] and time.time() - t0 < 3
    j3 = c.run("/api/test/slow", ids=[f["id"]], wait=False)  # cancelled job no longer blocks a retry
    assert j3["id"] != j1["id"]
    c.post(f"/api/jobs/{j3['id']}/cancel")
    c.wait(j3["id"])


def test_cancel_cleans_up_work_files(slow_api, tmp):
    from app.state import get_services

    f = slow_api.upload("a.pdf", pdf_bytes(tmp, 1))
    j = slow_api.run("/api/test/slow", ids=[f["id"]], wait=False)
    time.sleep(0.2)
    slow_api.post(f"/api/jobs/{j['id']}/cancel")
    slow_api.wait(j["id"])
    time.sleep(0.2)
    assert not (get_services().settings.work_dir / j["id"]).exists()


# ---------------------------------------------------------------- rate limiting
def test_rate_limit_applies_per_client(monkeypatch, tmp):
    for k, v in ENV_DEFAULTS.items():
        monkeypatch.setenv(k, v)
    app = build_app(RATE_LIMIT_MUTATING_PER_MIN=3)
    a, b = Client(app, "1.1.1.1"), Client(app, "2.2.2.2")
    pdf = pdf_bytes(tmp, 1)
    codes = [a.post("/api/files", files=[("files", "a.pdf", pdf)]).status for _ in range(5)]
    assert codes == [201, 201, 201, 429, 429]
    r = a.post("/api/files", files=[("files", "a.pdf", pdf)])
    assert r.error["code"] == "rate_limited" and int(r.headers["retry-after"]) >= 1
    assert b.post("/api/files", files=[("files", "a.pdf", pdf)]).status == 201
    assert a.get("/api/health").status == 200  # reads are limited separately


# ------------------------------------------------------------------- accounts
def test_account_lifecycle(monkeypatch, tmp):
    for k, v in ENV_DEFAULTS.items():
        monkeypatch.setenv(k, v)
    c = Client(build_app(EXPOSE_RESET_TOKEN=1))
    assert c.get("/api/auth/me").status == 401
    assert c.post("/api/auth/register", json={"email": "nope", "password": "longenough1"}).status == 422
    assert c.post("/api/auth/register", json={"email": "a@b.co", "password": "short"}).error["code"] == "weak_password"
    reg = c.post("/api/auth/register", json={"email": "Ada@Example.com", "password": "correct horse"})
    assert reg.status == 201
    assert c.post("/api/auth/register", json={"email": "ada@example.com", "password": "correct horse"}).status == 409
    tok = reg.json()["token"]
    auth = {"Authorization": f"Bearer {tok}"}
    assert c.get("/api/auth/me", headers=auth).json()["user"]["email"] == "Ada@Example.com"
    assert c.get("/api/auth/me", headers={"Authorization": "Bearer " + tok[:-3] + "abc"}).status == 401
    assert c.post("/api/auth/login", json={"email": "ada@example.com", "password": "wrong"}).status == 401
    login = c.post("/api/auth/login", json={"email": "ada@example.com", "password": "correct horse"})
    assert login.status == 200

    # processing while signed in records history; anonymous use still works
    pdf = pdf_bytes(tmp, 2)
    job = c.run("/api/pdf/rotate", files=[("my.pdf", pdf)], options={"angle": 90}, headers=auth)
    anon = c.run("/api/pdf/rotate", files=[("my.pdf", pdf)], options={"angle": 180})
    assert job["status"] == anon["status"] == "done"
    time.sleep(0.2)
    hist = c.get("/api/me/history", headers=auth).json()["items"]
    assert len(hist) == 1 and hist[0]["op"] == "rotate" and hist[0]["outputs"][0]["name"] == "my_rotated.pdf"

    # personal workspace
    out_id = job["outputs"][0]["id"]
    saved = c.post("/api/me/files", json={"file_id": out_id}, headers=auth)
    assert saved.status == 201
    assert len(c.get("/api/me/files", headers=auth).json()["files"]) == 1
    assert c.get(f"/api/me/files/{out_id}/download").status == 401
    assert c.get(f"/api/me/files/{out_id}/download", headers=auth).status == 200
    reopened = c.post(f"/api/me/files/{out_id}/open", headers=auth)
    assert reopened.status == 201 and reopened.json()["id"] != out_id
    assert c.get(f"/api/files/{reopened.json()['id']}/info").json()["pages"] == 2
    other = c.post("/api/auth/register", json={"email": "bob@example.com", "password": "another one 1"}).json()
    assert c.get(f"/api/me/files/{out_id}/download", headers={"Authorization": "Bearer " + other["token"]}).status == 404
    assert c.delete(f"/api/me/files/{out_id}", headers=auth).status == 200
    assert c.get("/api/me/files", headers=auth).json()["files"] == []
    assert c.delete("/api/me/history", headers=auth).status == 200

    # password change invalidates old tokens
    r = c.post("/api/auth/password", json={"old_password": "correct horse", "new_password": "new password 9"}, headers=auth)
    assert r.status == 200
    assert c.get("/api/auth/me", headers=auth).status == 401
    new_auth = {"Authorization": "Bearer " + r.json()["token"]}
    assert c.get("/api/auth/me", headers=new_auth).status == 200

    # reset flow (token only exposed in dev mode; unknown emails look identical)
    unknown = c.post("/api/auth/forgot", json={"email": "ghost@example.com"}).json()
    assert "dev_reset_token" not in unknown
    forgot = c.post("/api/auth/forgot", json={"email": "ada@example.com"}).json()
    assert c.post("/api/auth/reset", json={"token": "bad", "password": "whatever 123"}).status == 422
    assert c.post("/api/auth/reset", json={"token": forgot["dev_reset_token"], "password": "reset password 1"}).status == 200
    assert c.post("/api/auth/reset", json={"token": forgot["dev_reset_token"], "password": "reset password 2"}).status == 422
    assert c.post("/api/auth/login", json={"email": "ada@example.com", "password": "reset password 1"}).status == 200

    assert c.request("DELETE", "/api/auth/account", json={"password": "bad"}, headers=new_auth).status == 401
    relog = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "ada@example.com", "password": "reset password 1"}).json()["token"]}
    assert c.request("DELETE", "/api/auth/account", json={"password": "reset password 1"}, headers=relog).status == 200
    assert c.post("/api/auth/login", json={"email": "ada@example.com", "password": "reset password 1"}).status == 401
