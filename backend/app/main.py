import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.config import get_settings
from app.logging_config import configure_logging

settings = get_settings()
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings.assert_secure()
    scheduler = None
    if settings.run_scheduler:
        from app.scheduler import build_scheduler
        scheduler = build_scheduler()
        scheduler.start()
        log.info("Scheduler running in the API process (RUN_SCHEDULER=true)")
    yield
    if scheduler is not None:
        from app.scheduler import shutdown_pools
        scheduler.shutdown(wait=False)
        shutdown_pools()


app = FastAPI(title="ApplyPilot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)


class _BodyTooLarge(Exception):
    pass


class BodySizeLimit:
    """Caps request bodies while they stream in, so a body sent without Content-Length
    (chunked) can't be spooled to disk past the limit. Uploads get 1 MB of form overhead."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, send):
        response = JSONResponse(status_code=413, content={"detail": f"Request too large (limit {settings.max_upload_mb} MB)"})
        await send({"type": "http.response.start", "status": 413, "headers": response.raw_headers})
        await send({"type": "http.response.body", "body": response.body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        length = dict(scope.get("headers") or []).get(b"content-length", b"")
        if length.isdigit() and int(length) > self.max_bytes:
            return await self._reject(send)

        received, exceeded, replaced = 0, False, False

        async def limited_receive():
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message):
            nonlocal replaced
            # Body parsers may turn the abort into their own 400/500; answer 413 instead.
            if exceeded:
                if message["type"] == "http.response.start" and not replaced:
                    replaced = True
                    await self._reject(send)
                return
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            if not replaced:
                await self._reject(send)


app.add_middleware(BodySizeLimit, max_bytes=(settings.max_upload_mb + 1) * 1024 * 1024)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(api_router)


@app.get("/health")
def health() -> dict:
    """Public liveness plus per-task timing and error counts. Error details stay in the logs."""
    from app.scheduler import status
    return {"status": "ok", "scheduler_in_process": settings.run_scheduler, "tasks": status}
