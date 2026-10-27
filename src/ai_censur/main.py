from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from scalar_fastapi import get_scalar_api_reference

from ai_censur.api.auth_router import router as auth_router
from ai_censur.api.router import router
from ai_censur.api.user_router import router as user_router
from ai_censur.config import get_jwt_settings
from ai_censur.database.session import check_database_connection, dispose_engine
from ai_censur.utils.constants import UPLOAD_DIR, UPLOADS_URL_PATH
from ai_censur.utils.system import ensure_ffmpeg_available

API_DESCRIPTION = """
Upload an audio file and receive a censored copy in which profane words are
replaced with a beep.

**Pipeline:** upload -> WhisperX transcription and alignment -> profanity
detection -> beep over flagged words -> censored file stored in `Uploads/` ->
both file paths recorded in the database.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    ensure_ffmpeg_available()
    get_jwt_settings()  # fail fast when JWT_SECRET is missing
    await check_database_connection()
    try:
        yield
    finally:
        await dispose_engine()


app = FastAPI(
    title="AI Censur",
    description=API_DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount(UPLOADS_URL_PATH, StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.include_router(router)
app.include_router(user_router)
app.include_router(auth_router)


@app.get("/docs", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title="AI Censur API Reference",
    )
