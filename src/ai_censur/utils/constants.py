import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_DIR = PROJECT_ROOT / "Uploads"
SOUND_EFFECT_DIR = PROJECT_ROOT / "SoundEffects"
UPLOADS_URL_PATH = "/uploads"
CENSORED_PREFIX = "Censored_"
MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024
# Sound effects are short clips, so they get a much tighter cap than full recordings.
MAX_SOUND_EFFECT_SIZE_BYTES = 5 * 1024 * 1024
MAX_SOUND_EFFECT_NAME_LENGTH = 100
MAX_USER_WORDS = 200
MAX_USER_WORD_LENGTH = 50
READ_CHUNK_SIZE_BYTES = 1024 * 1024
ALLOWED_AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".flac", ".ogg"})
MAX_STEM_LENGTH = 100
MAX_NAME_COLLISION_ATTEMPTS = 1000
# Argon2 has no 72-byte limit like bcrypt; the cap only bounds hashing cost per request.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
UNSAFE_CHARS = re.compile(r"[^\w.\- ]")
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10))}
    | {f"LPT{i}" for i in range(1, 10)}
)
