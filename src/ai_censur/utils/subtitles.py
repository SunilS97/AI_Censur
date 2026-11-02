from collections.abc import Iterable, Mapping
from typing import Any

from ai_censur.utils.constants import (
    SUBTITLE_MAX_CUE_SECONDS,
    SUBTITLE_MAX_CUE_WORDS,
    SUBTITLE_MAX_GAP_SECONDS,
)

_SENTENCE_END = (".", "!", "?")


def mask_word(word: str, symbol: str, visible_chars: int) -> str:
    """Mask a word, keeping its first `visible_chars` letters or digits visible.

    Punctuation stays as it is. At least one character is always masked, so a word
    shorter than `visible_chars` is never shown in full.
    """
    positions = [index for index, char in enumerate(word) if char.isalnum()]
    if not positions:
        return word
    visible = min(visible_chars, len(positions) - 1)
    masked = set(positions[visible:])
    return "".join(
        symbol if index in masked else char for index, char in enumerate(word)
    )


def format_timestamp(seconds: float) -> str:
    """Format seconds as the SRT timestamp `HH:MM:SS,mmm`."""
    total_ms = round(max(seconds, 0.0) * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _timed_words(
    words: Iterable[Mapping[str, Any]], symbol: str, visible_chars: int
) -> list[tuple[str, float, float]]:
    """Return (text, start, end) per word with flagged words masked.

    The aligner sometimes leaves a word untimed (for example a number); it then
    borrows the previous word's end so the subtitle order and text are kept.
    """
    result: list[tuple[str, float, float]] = []
    last_end = 0.0
    for word in words:
        text = word.get("word")
        if not isinstance(text, str) or not text.strip():
            continue
        text = " ".join(text.split())
        if word.get("flagged"):
            text = mask_word(text, symbol, visible_chars)
        start = word.get("start")
        end = word.get("end")
        start = float(start) if isinstance(start, int | float) else last_end
        end = float(end) if isinstance(end, int | float) else start
        end = max(end, start)
        result.append((text, start, end))
        last_end = end
    return result


def build_srt(
    words: Iterable[Mapping[str, Any]], symbol: str, visible_chars: int
) -> str:
    """Group the (masked) words into subtitle cues and render them as SRT."""
    cues: list[list[tuple[str, float, float]]] = []
    for item in _timed_words(words, symbol, visible_chars):
        start = item[1]
        if cues:
            current = cues[-1]
            previous_text, _, previous_end = current[-1]
            if (
                len(current) >= SUBTITLE_MAX_CUE_WORDS
                or start - current[0][1] > SUBTITLE_MAX_CUE_SECONDS
                or start - previous_end > SUBTITLE_MAX_GAP_SECONDS
                or previous_text.endswith(_SENTENCE_END)
            ):
                cues.append([item])
            else:
                current.append(item)
        else:
            cues.append([item])

    blocks = [
        f"{number}\n"
        f"{format_timestamp(cue[0][1])} --> {format_timestamp(cue[-1][2])}\n"
        f"{' '.join(text for text, _, _ in cue)}\n"
        for number, cue in enumerate(cues, start=1)
    ]
    return "\n".join(blocks)
