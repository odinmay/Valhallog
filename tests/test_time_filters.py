from datetime import date, time, timezone

from valhallog.filters import filter_lines
from valhallog.time_filters import TimeWindow, parse_log_timestamp


def test_time_filter_uses_inclusive_minute_boundaries() -> None:
    window = TimeWindow.from_values(date(2026, 9, 14), time(17), 5)
    lines = [
        "2026-09-14T16:54:59 INFO: before",
        "2026-09-14T16:55:00 INFO: start",
        "2026-09-14T17:00:00 INFO: center",
        "2026-09-14T17:05:00 INFO: end",
        "2026-09-14T17:05:01 INFO: after",
        "INFO: no timestamp",
    ]

    assert filter_lines(lines, "all", window) == lines[1:4]


def test_time_only_and_syslog_timestamps_use_selected_date() -> None:
    selected = date(2026, 9, 14)

    time_only = parse_log_timestamp("17:00:00 INFO: started", selected)
    syslog = parse_log_timestamp("Sep 14 17:00:00 INFO: started", selected)

    assert time_only is not None
    assert syslog is not None
    assert time_only.date() == selected
    assert syslog.date() == selected
    assert time_only.hour == syslog.hour == 17


def test_explicit_timestamp_offset_is_preserved() -> None:
    parsed = parse_log_timestamp(
        "2026-09-14T17:00:00Z INFO: started",
        date(2026, 9, 14),
    )

    assert parsed is not None
    assert parsed.tzinfo == timezone.utc
