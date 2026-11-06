"""Four-row Joi::Observer wordmark in terminal character cells."""

import re


# Each triple is Joi, the double colon, and Observer, including their shadows.
WORDMARK_ROWS = (
    (" ▀▀█╷ ▄▄╮  ▀╮ ", "    ", "▄▀▀▄╮█╮    ▄▄▄╮ ▄▄╮ ▄╮▄▄╮▄╮  ▄╮ ▄▄╮ ▄╮▄▄╮"),
    ("   █│█  █╮▀█│ ", "▀ ▀ ", "█  █│█▀▀▄╮▀▄▄╭╯█▄▄█╮█▀╭─╯█│  █│█▄▄█╮█▀╭─╯"),
    ("▝▙▄▛│▀▄▄▀│▄█▄╮", "▀ ▀ ", "▀▄▄▀│█▄▄▀│▄▄▄▀╮▀▄▄▄│█╭╯  ╰▀▄▀╭╯▀▄▄▄│█╭╯  "),
    (" ╶──╯╰───╯╰──╯", "    ", "╰───╯╰───╯╰───╯╰───╯╰╯    ╰──╯ ╰───╯╰╯   "),
)
_SHADOW = "─│╭╮╰╯╷╶"
_STROKES = re.compile(f"[{_SHADOW}]+|[^{_SHADOW} ]+")


def wordmark_runs():
    """Yield terminal positions, contiguous strokes and their theme roles."""
    for row, bands in enumerate(WORDMARK_ROWS):
        column = 0
        for band, face in zip(bands, ("secondary", "muted", "primary"), strict=True):
            for match in _STROKES.finditer(band):
                text = match.group()
                role = "brand_shadow" if text[0] in _SHADOW else face
                yield row, column + match.start(), text, role
            column += len(band)
