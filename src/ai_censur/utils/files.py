from pathlib import Path, PureWindowsPath

from fastapi import HTTPException, UploadFile, status

from ai_censur.utils.constants import (
    MAX_NAME_COLLISION_ATTEMPTS,
    MAX_STEM_LENGTH,
    MAX_UPLOAD_SIZE_BYTES,
    READ_CHUNK_SIZE_BYTES,
    UNSAFE_CHARS,
    WINDOWS_RESERVED_NAMES,
)


async def read_upload(file: UploadFile) -> bytes:
    content = bytearray()
    while chunk := await file.read(READ_CHUNK_SIZE_BYTES):
        content.extend(chunk)
        if len(content) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"File exceeds the maximum size of "
                    f"{MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB."
                ),
            )
    return bytes(content)


def sanitize_stem(filename: str) -> str:
    # PureWindowsPath treats both "/" and "\" as separators, dropping any directory part.
    stem = PureWindowsPath(filename).stem
    stem = UNSAFE_CHARS.sub("_", stem).strip(" ._")[:MAX_STEM_LENGTH]
    if not stem:
        return "audio"
    if stem.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:
        return f"_{stem}"
    return stem


def reserve_path(directory: Path, stem: str, extension: str) -> Path:
    """Exclusively create an empty file, appending _1, _2, ... when the name is taken."""
    directory.mkdir(parents=True, exist_ok=True)
    for counter in range(MAX_NAME_COLLISION_ATTEMPTS):
        name = f"{stem}{extension}" if counter == 0 else f"{stem}_{counter}{extension}"
        path = directory / name
        try:
            path.open("xb").close()
        except FileExistsError:
            continue
        return path
    raise FileExistsError(f"Could not find a free filename for {stem}{extension}")


def write_file(directory: Path, stem: str, extension: str, content: bytes) -> str:
    path = reserve_path(directory, stem, extension)
    try:
        path.write_bytes(content)
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return path.name


def remove_files(directory: Path, names: list[str]) -> None:
    """Best-effort removal of stored files, used to avoid orphans after a failure."""
    for name in names:
        (directory / name).unlink(missing_ok=True)
