from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from dsxa_sdk_py.client import AsyncDSXAClient
from dsxa_sdk_py.exceptions import DSXAError
from dsxa_sdk_py.models import ScanResponse

from .policy import classify_scan, sanitize_filename


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

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "baseUrl": self.base_url,
            "authToken": self.auth_token or "",
            "protectedEntity": self.protected_entity,
            "scanConcurrency": self.scan_concurrency,
        }

    def update(self, *, base_url: str, auth_token: str, protected_entity: int, scan_concurrency: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token or None
        self.protected_entity = protected_entity
        self.scan_concurrency = max(1, scan_concurrency)


class ConfigUpdate(BaseModel):
    baseUrl: str
    authToken: str = ""
    protectedEntity: int = 1
    scanConcurrency: int = 4


settings = Settings()
app = FastAPI(title="DSXA Loan Intake Demo")
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
INDEX_HTML = (TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")


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

@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_HTML


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "configured": bool(settings.base_url),
        "scan_concurrency": settings.scan_concurrency,
        "upload_dir": str(settings.upload_dir),
    }


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    return settings.to_public_dict()


@app.post("/api/config")
async def update_config(payload: ConfigUpdate) -> dict[str, Any]:
    if not payload.baseUrl.strip():
        raise HTTPException(status_code=400, detail="DSXA Base URL is required.")
    settings.update(
        base_url=payload.baseUrl.strip(),
        auth_token=payload.authToken.strip(),
        protected_entity=payload.protectedEntity,
        scan_concurrency=payload.scanConcurrency,
    )
    return {
        "message": "Configuration updated.",
        "config": settings.to_public_dict(),
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
        decision = classify_scan(response)
        if decision.accepted:
            destination = _allocate_destination(filename)
            await asyncio.to_thread(destination.write_bytes, payload)
            detail = f"Stored at {destination}"
        else:
            detail = response.verdict_details.reason or (
                "Executable files and unsafe content are not admitted into intake."
            )
        return {
          "filename": filename,
          "bucket": decision.bucket,
          "tone": decision.tone,
          "headline": decision.headline,
          "verdict": response.verdict.value,
          "detail": detail,
          "scan_guid": response.scan_guid,
          "scanDurationInMicroseconds": response.scan_duration_in_microseconds,
        }
    except DSXAError as exc:
        return {
            "filename": filename,
            "bucket": "review",
            "tone": "review",
            "headline": "Scanner error",
            "verdict": "Error",
            "detail": str(exc),
            "scan_guid": None,
            "scanDurationInMicroseconds": None,
        }
    finally:
        await upload.close()
