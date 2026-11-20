"""Single-line text and column widths for the target ncurses/libc locale.

Width queries never change the process locale or initialize curses. The cache
includes LC_CTYPE so a later locale change cannot reuse another locale's result.
Unrepresentable characters are rendered as ASCII placeholders, rather than
retaining a character whose terminal expansion is unknown.
"""

from functools import lru_cache
import locale
import unicodedata


@lru_cache(maxsize=1)
def _native_width():
    # Resolve the host libc only on first non-ASCII use. PyDLL keeps the GIL
    # during this tiny call, alongside Python's locale query and cache access.
    import ctypes

    try:
        function = ctypes.PyDLL(None).wcwidth
    except (AttributeError, OSError):
        return None
    function.argtypes = (ctypes.c_wchar,)
    function.restype = ctypes.c_int
    return function


@lru_cache(maxsize=16384)
def _character_width(character: str, ctype_locale: str) -> int:
    function = _native_width()
    return function(character) if function is not None else -1


def _cells(value: str):
    ctype_locale = locale.setlocale(locale.LC_CTYPE)
    for character in value:
        if unicodedata.category(character).startswith("C") or character in "\u2028\u2029":
            yield " ", 1
        elif " " <= character <= "~":
            yield character, 1
        else:
            width = _character_width(character, ctype_locale)
            yield ("?", 1) if width < 0 else (character, width)


def display_text(value: str) -> str:
    """Return safe single-line text, suppressing leading zero-width marks."""
    result = []
    has_base = False
    for character, width in _cells(value):
        if width or has_base:
            result.append(character)
        if width:
            has_base = True
    return "".join(result)


def display_width(value: str) -> int:
    """Count columns of the same sanitized characters that are rendered."""
    return sum(width for _, width in _cells(value))


def clip_text(value: str, width: int) -> str:
    """Fit a sanitized prefix, retaining zero-width suffixes on accepted bases."""
    if width <= 0:
        return ""
    result = []
    used = 0
    for character, columns in _cells(value):
        if used + columns > width:
            break
        if used or columns:
            result.append(character)
        used += columns
    return "".join(result)
