import hmac
import logging
import sqlite3

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from progress_endpoint.config import Config
from progress_endpoint.events import InvalidEvent, is_document, parse_session
from progress_endpoint.logs import LOGGER_NAME
from progress_endpoint.store import Store

MAX_BODY_BYTES = 1024

logger = logging.getLogger(LOGGER_NAME)


async def read_capped(request: Request) -> bytes:
    """The whole body, counted on the stream: Content-Length can be absent or wrong."""
    body = bytearray()
    try:
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_BODY_BYTES:
                raise InvalidEvent("body is over 1 KB")
    except ClientDisconnect:
        raise InvalidEvent("client disconnected mid-body") from None
    return bytes(body)


def create_app(config: Config) -> FastAPI:
    store = Store(config.db_path)
    key = config.api_key.encode()

    def require_token(request: Request) -> None:
        # Raw header bytes: compare_digest raises on non-ASCII str, and a client controls
        # this value. As a dependency it runs before the body is read.
        header = next((v for k, v in request.scope["headers"] if k == b"authorization"), b"")
        scheme, _, token = header.partition(b" ")
        if scheme.lower() != b"bearer" or not hmac.compare_digest(token, key):
            raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})

    api = APIRouter(dependencies=[Depends(require_token)])

    @api.post("/v1/events/reader-session")
    async def reader_session(request: Request) -> Response:
        # A failing status would stall the device queue, and no retry can fix these.
        try:
            session = parse_session(await read_capped(request))
        except InvalidEvent as error:
            logger.warning("event_discarded", extra={"reason": str(error)})
            return Response(status_code=202)

        stored = await run_in_threadpool(store.add_session, session)
        logger.info(
            "event_stored" if stored else "event_replayed",
            extra={"id": session.id, "document": session.document},
        )
        return Response(status_code=204)

    @api.get("/v1/progress")
    def all_progress() -> dict:
        return {"documents": [position.as_json() for position in store.latest()]}

    @api.get("/v1/progress/{document}")
    def one_document(document: str) -> dict:
        position = store.latest_for(document) if is_document(document) else None
        if position is None:
            raise HTTPException(404)
        return position.as_json()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(api)

    @app.get("/healthz")
    def healthz() -> dict:
        store.check()
        return {"status": "ok"}

    @app.exception_handler(sqlite3.Error)
    def database_fault(request: Request, error: sqlite3.Error) -> JSONResponse:
        # A failing status is right here: the device keeps the event and retries it.
        logger.error("database_fault", exc_info=error)
        return JSONResponse({"status": "unavailable"}, status_code=503)

    return app
