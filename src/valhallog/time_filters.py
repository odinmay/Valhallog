"""Timestamp parsing and inclusive time-window filtering."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


TIMESTAMP_PATTERN = re.compile(
    r"\b(?:"
    r"\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}"
    r"(?:[.,]\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?"
    r"|\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"
    r")\b",
    re.IGNORECASE,
)


def local_timezone() -> tzinfo:
    """Return the machine's current local timezone."""
    try:
        zoneinfo_root = Path("/usr/share/zoneinfo")
        localtime = Path("/etc/localtime").resolve()
        zone_key = localtime.relative_to(zoneinfo_root).as_posix()
        return ZoneInfo(zone_key)
    except (OSError, ValueError, ZoneInfoNotFoundError):
        return datetime.now().astimezone().tzinfo or timezone.utc


def parse_log_timestamp(
    line: str,
    selected_date: date,
    default_timezone: tzinfo | None = None,
) -> datetime | None:
    """Parse the first supported timestamp in a log line.

    Explicit offsets are preserved. Timestamp formats without a timezone use
    the machine's local timezone and time-only/syslog formats use
    ``selected_date``.
    """
    match = TIMESTAMP_PATTERN.search(line)
    if match is None:
        return None

    timestamp = match.group()
    timezone = default_timezone or local_timezone()
    if re.match(r"^\d{4}[-/]", timestamp):
        normalized = timestamp.replace("/", "-").replace(",", ".")
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return (
            parsed
            if parsed.tzinfo is not None
            else parsed.replace(tzinfo=timezone)
        )

    if timestamp[:3].casefold() in {
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
    }:
        try:
            parsed = datetime.strptime(
                f"{timestamp} {selected_date.year}",
                "%b %d %H:%M:%S %Y",
            )
        except ValueError:
            return None
        return parsed.replace(year=selected_date.year, tzinfo=timezone)

    normalized = timestamp.replace(",", ".")
    try:
        parsed_time = time.fromisoformat(normalized)
    except ValueError:
        return None
    return datetime.combine(selected_date, parsed_time, tzinfo=timezone)


@dataclass(frozen=True)
class TimeWindow:
    """An inclusive window centered on a selected local time."""

    center: datetime
    minutes: int = 5

    def __post_init__(self) -> None:
        if self.center.tzinfo is None:
            raise ValueError("TimeWindow.center must be timezone-aware")
        if self.minutes < 0:
            raise ValueError("TimeWindow.minutes must not be negative")

    @classmethod
    def from_values(
        cls, selected_date: date, selected_time: time, minutes: int
    ) -> "TimeWindow":
        timezone = selected_time.tzinfo or local_timezone()
        center = datetime.combine(selected_date, selected_time, tzinfo=timezone)
        return cls(center=center, minutes=minutes)

    @property
    def start(self) -> datetime:
        return self.center - timedelta(minutes=self.minutes)

    @property
    def end(self) -> datetime:
        return self.center + timedelta(minutes=self.minutes)

    def contains(self, timestamp: datetime) -> bool:
        """Return whether a timestamp falls within the inclusive window."""
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=self.center.tzinfo)
        return self.start <= timestamp <= self.end

    def matches_line(self, line: str) -> bool:
        """Return whether a line has a timestamp inside this window."""
        timestamp = parse_log_timestamp(line, self.center.date(), self.center.tzinfo)
        return timestamp is not None and self.contains(timestamp)

    def label(self) -> str:
        """Return a compact label suitable for status text."""
        return f"{self.center:%Y-%m-%d %H:%M:%S} ± {self.minutes} min"
