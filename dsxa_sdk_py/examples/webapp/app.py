from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from dsxa_sdk_py.client import AsyncDSXAClient
from dsxa_sdk_py.exceptions import DSXAError
from dsxa_sdk_py.models import ScanResponse

from .policy import classify_verdict, sanitize_filename


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


class Settings:
    def __init__(self) -> None:
        self.base_url = os.getenv("DSXA_BASE_URL", "").rstrip("/")
        self.auth_token = os.getenv("DSXA_AUTH_TOKEN")
        self.protected_entity = int(os.getenv("DSXA_PROTECTED_ENTITY", "1"))
        self.verify_tls = _env_bool("DSXA_VERIFY_TLS", True)
        self.scan_concurrency = max(1, int(os.getenv("WEBAPP_SCAN_CONCURRENCY", "4")))
        self.upload_dir = Path(
            os.getenv("WEBAPP_UPLOAD_DIR", str(Path.cwd() / ".demo_uploads" / "accepted"))
        )


settings = Settings()
app = FastAPI(title="DSXA Loan Intake Demo")


def _allocate_destination(filename: str) -> Path:
    candidate = settings.upload_dir / filename
    if not candidate.exists():
        return candidate

    stem = Path(filename).stem or "uploaded-file"
    suffix = Path(filename).suffix
    counter = 2
    while True:
        candidate = settings.upload_dir / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Loan Intake Document Review</title>
  <style>
    :root {
      --ink: #18212d;
      --muted: #5b6471;
      --line: rgba(24, 33, 45, 0.12);
      --paper: #fffaf2;
      --panel: rgba(255, 255, 255, 0.82);
      --navy: #143a52;
      --gold: #d2a44c;
      --mint: #dff3e7;
      --mint-ink: #1f6a42;
      --rose: #fbe2e0;
      --rose-ink: #992f2a;
      --sand: #f3ead7;
      --shadow: 0 24px 60px rgba(20, 58, 82, 0.14);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(210, 164, 76, 0.16), transparent 35%),
        linear-gradient(180deg, #f4efe5 0%, #fbf7ef 48%, #f3ebde 100%);
      min-height: 100vh;
    }
    .shell {
      width: min(1080px, calc(100vw - 32px));
      margin: 32px auto;
      padding: 24px;
    }
    .hero {
      display: grid;
      gap: 18px;
      grid-template-columns: 1.2fr 0.8fr;
      align-items: stretch;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }
    .headline {
      padding: 28px;
    }
    .eyebrow {
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 12px;
      color: var(--navy);
      margin-bottom: 14px;
      font-family: "Avenir Next Condensed", "Franklin Gothic Medium", sans-serif;
    }
    h1 {
      margin: 0 0 14px;
      font-size: clamp(2.2rem, 4vw, 4.2rem);
      line-height: 0.95;
      font-weight: 700;
    }
    .lede, .meta, button, input {
      font-family: "Avenir Next", "Segoe UI", sans-serif;
    }
    .lede {
      color: var(--muted);
      line-height: 1.6;
      max-width: 60ch;
      margin: 0;
    }
    .ledger {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      padding: 20px;
      background: linear-gradient(180deg, rgba(20, 58, 82, 0.95), rgba(20, 58, 82, 0.82));
      color: white;
      overflow: hidden;
      position: relative;
    }
    .ledger::after {
      content: "";
      position: absolute;
      inset: auto -15% -30% auto;
      width: 220px;
      height: 220px;
      border-radius: 999px;
      background: rgba(210, 164, 76, 0.2);
    }
    .stat {
      border: 1px solid rgba(255,255,255,0.14);
      border-radius: 18px;
      padding: 18px;
      background: rgba(255,255,255,0.06);
      z-index: 1;
    }
    .stat strong {
      display: block;
      font-size: 2rem;
      margin-bottom: 8px;
    }
    .uploader {
      margin-top: 20px;
      padding: 24px;
    }
    form {
      display: grid;
      gap: 16px;
    }
    input[type="file"] {
      border: 1px dashed var(--line);
      background: rgba(255,255,255,0.7);
      border-radius: 18px;
      padding: 20px;
      width: 100%;
    }
    button {
      border: 0;
      border-radius: 999px;
      background: linear-gradient(135deg, var(--navy), #245f84);
      color: white;
      padding: 14px 20px;
      font-size: 15px;
      font-weight: 600;
      width: fit-content;
      cursor: pointer;
    }
    button:disabled {
      opacity: 0.65;
      cursor: wait;
    }
    .meta {
      color: var(--muted);
      font-size: 14px;
    }
    .results {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 20px;
      margin-top: 20px;
    }
    .bucket {
      padding: 20px;
    }
    .bucket h2 {
      margin: 0 0 12px;
      font-size: 1.2rem;
    }
    .list {
      display: grid;
      gap: 12px;
    }
    .item {
      border-radius: 18px;
      padding: 14px 16px;
      border: 1px solid var(--line);
      background: white;
    }
    .item.accepted { background: var(--mint); color: var(--mint-ink); }
    .item.rejected { background: var(--rose); color: var(--rose-ink); }
    .item.review { background: var(--sand); }
    .item strong {
      display: block;
      margin-bottom: 6px;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      font-size: 15px;
    }
    .item span {
      display: block;
      font-size: 14px;
      line-height: 1.5;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
    }
    .empty {
      color: var(--muted);
      font-family: "Avenir Next", "Segoe UI", sans-serif;
    }
    @media (max-width: 860px) {
      .hero, .results { grid-template-columns: 1fr; }
      .shell { width: min(100vw - 20px, 1080px); margin: 10px auto 24px; padding: 10px; }
      .headline, .uploader, .bucket, .ledger { padding: 18px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <article class="panel headline">
        <div class="eyebrow">Loan Processing Intake</div>
        <h1>Review applicant documents before they enter the file room.</h1>
        <p class="lede">
          Upload supporting documents, scan each file with DSXA on the server, and only admit clean files into the intake queue.
        </p>
      </article>
      <aside class="panel ledger">
        <div class="stat"><strong id="count-total">0</strong><span>Files reviewed</span></div>
        <div class="stat"><strong id="count-accepted">0</strong><span>Accepted</span></div>
        <div class="stat"><strong id="count-rejected">0</strong><span>Rejected</span></div>
        <div class="stat"><strong id="count-review">0</strong><span>Needs review</span></div>
      </aside>
    </section>

    <section class="panel uploader">
      <form id="upload-form">
        <input id="files" name="files" type="file" multiple required />
        <button id="submit" type="submit">Scan And Intake</button>
        <div class="meta" id="status">Clean files will be written to the server intake folder after DSXA returns a benign verdict.</div>
      </form>
    </section>

    <section class="results">
      <article class="panel bucket">
        <h2>Accepted documents</h2>
        <div id="accepted" class="list"><div class="empty">No accepted files yet.</div></div>
      </article>
      <article class="panel bucket">
        <h2>Rejected or held</h2>
        <div id="rejected" class="list"><div class="empty">No rejected files yet.</div></div>
      </article>
    </section>
  </main>

  <script>
    const form = document.getElementById("upload-form");
    const input = document.getElementById("files");
    const submit = document.getElementById("submit");
    const status = document.getElementById("status");
    const accepted = document.getElementById("accepted");
    const rejected = document.getElementById("rejected");

    function setCounts(summary) {
      document.getElementById("count-total").textContent = String(summary.total);
      document.getElementById("count-accepted").textContent = String(summary.accepted);
      document.getElementById("count-rejected").textContent = String(summary.rejected);
      document.getElementById("count-review").textContent = String(summary.review);
    }

    function renderItems(target, items, fallback) {
      if (!items.length) {
        target.innerHTML = `<div class="empty">${fallback}</div>`;
        return;
      }
      target.innerHTML = items.map((item) => `
        <div class="item ${item.bucket}">
          <strong>${item.filename}</strong>
          <span>${item.headline}</span>
          <span>Verdict: ${item.verdict}</span>
          <span>${item.detail}</span>
        </div>
      `).join("");
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!input.files.length) {
        status.textContent = "Select at least one file.";
        return;
      }
      submit.disabled = true;
      status.textContent = "Scanning files with DSXA...";

      const data = new FormData();
      for (const file of input.files) {
        data.append("files", file);
      }

      try {
        const response = await fetch("/api/uploads", { method: "POST", body: data });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "Upload failed.");
        }
        setCounts(payload.summary);
        renderItems(accepted, payload.accepted, "No accepted files in this batch.");
        renderItems(rejected, payload.rejected, "No rejected or held files in this batch.");
        status.textContent = payload.message;
        form.reset();
      } catch (error) {
        status.textContent = error.message || "Upload failed.";
      } finally {
        submit.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    if not settings.base_url:
        raise HTTPException(
            status_code=500,
            detail="Set DSXA_BASE_URL before starting the demo app.",
        )
    return PAGE


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "configured": bool(settings.base_url),
        "scan_concurrency": settings.scan_concurrency,
        "upload_dir": str(settings.upload_dir),
    }


@app.post("/api/uploads")
async def upload_and_scan(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    if not settings.base_url:
        raise HTTPException(status_code=500, detail="DSXA_BASE_URL is not configured.")
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required.")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(settings.scan_concurrency)

    async with AsyncDSXAClient(
        base_url=settings.base_url,
        auth_token=settings.auth_token,
        default_protected_entity=settings.protected_entity,
        verify_tls=settings.verify_tls,
    ) as client:
        results = await asyncio.gather(
            *(scan_one_upload(upload, client, semaphore) for upload in files)
        )

    accepted = [result for result in results if result["bucket"] == "accepted"]
    rejected = [result for result in results if result["bucket"] != "accepted"]
    summary = {
        "total": len(results),
        "accepted": len(accepted),
        "rejected": len([result for result in results if result["bucket"] == "rejected"]),
        "review": len([result for result in results if result["bucket"] == "review"]),
    }
    return {
        "message": f"Reviewed {summary['total']} file(s). Accepted {summary['accepted']}, held back {summary['total'] - summary['accepted']}.",
        "summary": summary,
        "accepted": accepted,
        "rejected": rejected,
    }


async def scan_one_upload(
    upload: UploadFile,
    client: AsyncDSXAClient,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    filename = sanitize_filename(upload.filename or "")
    try:
        payload = await upload.read()
        async with semaphore:
            response: ScanResponse = await client.scan_binary(
                payload,
                custom_metadata=f"loan-intake:{filename}",
            )
        decision = classify_verdict(response.verdict)
        if decision.accepted:
            destination = _allocate_destination(filename)
            await asyncio.to_thread(destination.write_bytes, payload)
            detail = f"Stored at {destination}"
        else:
            detail = response.verdict_details.reason or "This file was not admitted into intake."
        return {
            "filename": filename,
            "bucket": decision.bucket,
            "headline": decision.headline,
            "verdict": response.verdict.value,
            "detail": detail,
            "scan_guid": response.scan_guid,
        }
    except DSXAError as exc:
        return {
            "filename": filename,
            "bucket": "review",
            "headline": "Scanner error",
            "verdict": "Error",
            "detail": str(exc),
            "scan_guid": None,
        }
    finally:
        await upload.close()
