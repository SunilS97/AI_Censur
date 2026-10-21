from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import anyio
import anyio.to_thread
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from scalar_fastapi import get_scalar_api_reference

from ai_censur.api.router import router
from ai_censur.audio_censor import AudioCensor
from ai_censur.database.session import create_db_and_tables, dispose_engine
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
    await anyio.to_thread.run_sync(create_db_and_tables)
    # Models are expensive to load, so build the AudioCensor once per process.
    app.state.audio_censor = await anyio.to_thread.run_sync(AudioCensor)
    try:
        yield
    finally:
        await anyio.to_thread.run_sync(dispose_engine)


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


@app.get("/docs", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title="AI Censur API Reference",
    )
