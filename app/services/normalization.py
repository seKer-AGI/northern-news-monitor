"""Conservative post-text normalization.

The goal is tidy whitespace, not rewriting content: punctuation, Unicode,
emoji (including ZWJ sequences), URLs and paragraph breaks are preserved.
"""

from __future__ import annotations

import re
import unicodedata

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_INLINE_WS_RE = re.compile(r"[^\S\n]+")  # any whitespace except newline
_MANY_NEWLINES_RE = re.compile(r"\n{3,}")


def normalize_text(text: str | None, *, remove_urls: bool = False) -> str:
    if not text:
        return ""
    # NFC composes equivalent code-point sequences without changing meaning.
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" ", "\n").replace(" ", "\n\n")
    if remove_urls:
        text = _URL_RE.sub("", text)
    lines = [_INLINE_WS_RE.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _MANY_NEWLINES_RE.sub("\n\n", text)
    return text.strip()
