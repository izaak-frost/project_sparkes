"""Private Apple Health upload service; place behind an HTTPS reverse proxy."""
import json
import secrets

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from support.config import Settings, load_settings
from .nutrition import export_nutrition, ingest_nutrition


MAX_BODY_BYTES = 1024 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    if len(settings.upload_token) < 32:
        raise ValueError("HEALTH_UPLOAD_TOKEN must contain at least 32 characters")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/apple-health")
    async def upload(request: Request):
        supplied = request.headers.get("authorization", "").encode("utf-8")
        expected = f"Bearer {settings.upload_token}".encode("utf-8")
        if not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Invalid upload token")
        if request.headers.get("content-type", "").split(";")[0].lower() != "application/json":
            raise HTTPException(415, "Use JSON export format")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY_BYTES:
                raise HTTPException(413, "Nutrition upload exceeds 1 MiB")
        try:
            payload = json.loads(body)
            count = await run_in_threadpool(ingest_nutrition, settings, payload)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(422, str(exc)) from None
        await run_in_threadpool(export_nutrition, settings)
        return {"accepted_totals": count}

    return app
