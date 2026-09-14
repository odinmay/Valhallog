"""Simple, source-aware log-level filtering for Valhallog."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .time_filters import TimeWindow

LEVELS = ("all", "debug", "info", "warning", "error", "critical")
_LEVEL_RANK = {level: rank for rank, level in enumerate(LEVELS)}
_TOKEN_LEVELS = (
    ("critical", re.compile(r"\b(?:CRITICAL|FATAL|ALERT|EMERG)\b", re.I)),
    ("error", re.compile(r"\b(?:ERROR|ERR)\b", re.I)),
    ("warning", re.compile(r"\b(?:WARN|WARNING)\b", re.I)),
    ("info", re.compile(r"\b(?:INFO|NOTICE)\b", re.I)),
    ("debug", re.compile(r"\b(?:DEBUG|DBG)\b", re.I)),
)


def normalize_level(level: str) -> str:
    """Return a supported lowercase level or raise a helpful error."""
    normalized = level.casefold()
    if normalized not in LEVELS:
        raise ValueError(f"unsupported log level: {level!r}")
    return normalized


def classify_line(line: str) -> str:
    """Classify a plain-text line using simple case-insensitive tokens."""
    for level, pattern in _TOKEN_LEVELS:
        if pattern.search(line):
            return level
    # Plain files have no universal severity format; unknown lines are Info.
    return "info"


def classify_token(token: str) -> str | None:
    """Return the severity represented by one recognized token."""
    for level, pattern in _TOKEN_LEVELS:
        if pattern.fullmatch(token):
            return level
    return None


def should_show(
    line: str,
    minimum_level: str,
    time_window: TimeWindow | None = None,
) -> bool:
    """Return whether a line meets the selected minimum severity."""
    level = normalize_level(minimum_level)
    return (
        (level == "all" or _LEVEL_RANK[classify_line(line)] >= _LEVEL_RANK[level])
        and (time_window is None or time_window.matches_line(line))
    )


def filter_lines(
    lines: Iterable[str],
    minimum_level: str,
    time_window: TimeWindow | None = None,
) -> list[str]:
    """Return lines that meet a plain-file severity filter."""
    return [line for line in lines if should_show(line, minimum_level, time_window)]
