"""Four-row Joi::Observer wordmark in terminal character cells."""

import re


# Each triple is Joi, the double colon, and Observer on the original 59×4 canvas.
WORDMARK_ROWS = (
    (" ▀▀█  ▄▄   ▀  ", "    ", "▄▀▀▄ █     ▄▄▄  ▄▄  ▄ ▄▄ ▄   ▄  ▄▄  ▄ ▄▄ "),
    ("   █ █  █ ▀█  ", "▀ ▀ ", "█  █ █▀▀▄ ▀▄▄  █▄▄█ █▀   █   █ █▄▄█ █▀   "),
    ("▝▙▄▛ ▀▄▄▀ ▄█▄ ", "▀ ▀ ", "▀▄▄▀ █▄▄▀ ▄▄▄▀ ▀▄▄▄ █     ▀▄▀  ▀▄▄▄ █    "),
    ("              ", "    ", "                                         "),
)
_STROKES = re.compile(r"[^ ]+")


def wordmark_runs():
    """Yield terminal positions, contiguous strokes and their theme roles."""
    for row, bands in enumerate(WORDMARK_ROWS):
        column = 0
        for band, face in zip(bands, ("secondary", "muted", "primary"), strict=True):
            for match in _STROKES.finditer(band):
                text = match.group()
                yield row, column + match.start(), text, face
            column += len(band)
