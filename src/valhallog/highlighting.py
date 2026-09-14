"""Rich text highlighting for log lines."""

from __future__ import annotations

import re

from rich.text import Text

from .filters import classify_token
from .time_filters import TIMESTAMP_PATTERN
_SEVERITY_TOKEN_PATTERN = re.compile(
    r"\b(?:CRITICAL|FATAL|ALERT|EMERG|ERROR|ERR|WARN|WARNING|INFO|NOTICE|DEBUG|DBG)\b",
    re.IGNORECASE,
)
_SEVERITY_STYLES = {
    "debug": "cyan",
    "info": "green",
    "warning": "yellow",
    "error": "red",
    "critical": "bold red",
}


def highlight_log_line(line: str) -> Text:
    """Style timestamps and severity tokens without changing message text."""
    highlighted = Text(line)

    for match in TIMESTAMP_PATTERN.finditer(line):
        highlighted.stylize("dim cyan", match.start(), match.end())

    for match in _SEVERITY_TOKEN_PATTERN.finditer(line):
        level = classify_token(match.group())
        if level is not None:
            highlighted.stylize(
                _SEVERITY_STYLES[level], match.start(), match.end()
            )

    return highlighted
