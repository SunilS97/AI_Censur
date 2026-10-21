import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_ffmpeg_available() -> None:
    """Fail fast if ffmpeg is missing, since WhisperX and pydub shell out to it.

    On Windows, winget installs update PATH only for newly opened terminals, so a
    long-running shell can miss a valid install; fall back to the winget location.
    """
    if shutil.which("ffmpeg"):
        return
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        winget_packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        for executable in sorted(winget_packages.glob("*/*/bin/ffmpeg.exe")):
            os.environ["PATH"] = f"{executable.parent}{os.pathsep}{os.environ['PATH']}"
            logger.info("ffmpeg not on PATH; using %s", executable)
            return
    raise RuntimeError(
        "ffmpeg was not found. Install it (for example "
        "'winget install Gyan.FFmpeg.Essentials') and restart the terminal "
        "before starting the server."
    )
