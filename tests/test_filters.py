import pytest

from valhallog.filters import classify_line, filter_lines, should_show


@pytest.mark.parametrize(
    ("line", "level"),
    [
        ("DEBUG: retrying", "debug"),
        ("notice: started", "info"),
        ("WARNING: low disk", "warning"),
        ("err: failed", "error"),
        ("FATAL: unavailable", "critical"),
        ("a line without a token", "info"),
    ],
)
def test_classify_line_uses_documented_tokens(line: str, level: str) -> None:
    assert classify_line(line) == level


def test_filter_lines_treats_unknown_lines_as_info() -> None:
    lines = [
        "DEBUG: details",
        "INFO: started",
        "WARNING: nearly full",
        "ERROR: failed",
        "CRITICAL: unavailable",
        "plain text line",
    ]

    assert filter_lines(lines, "all") == lines
    assert filter_lines(lines, "warning") == lines[2:5]
    assert filter_lines(lines, "error") == lines[3:5]
    assert filter_lines(lines, "critical") == lines[4:5]


def test_should_show_rejects_unknown_levels() -> None:
    assert should_show("plain text line", "all") is True
    assert should_show("plain text line", "info") is True
    assert should_show("plain text line", "warning") is False


def test_filter_rejects_unknown_level() -> None:
    with pytest.raises(ValueError, match="unsupported log level"):
        filter_lines(["INFO: started"], "verbose")
