from rich.text import Text

from valhallog.highlighting import highlight_log_line


def test_highlight_log_line_preserves_text_and_styles_timestamp_and_level() -> None:
    line = "2026-09-13T14:22:31.123Z ERROR: disk is nearly full"

    highlighted = highlight_log_line(line)

    assert isinstance(highlighted, Text)
    assert highlighted.plain == line
    assert [(span.start, span.end, span.style) for span in highlighted.spans] == [
        (0, 24, "dim cyan"),
        (25, 30, "red"),
    ]


def test_highlight_log_line_supports_time_only_and_syslog_timestamps() -> None:
    line = "Jan  4 09:15:27 warning: retrying connection at 09:15:28"

    highlighted = highlight_log_line(line)

    assert highlighted.plain == line
    assert sorted(
        (span.start, span.end, span.style) for span in highlighted.spans
    ) == [
        (0, 15, "dim cyan"),
        (16, 23, "yellow"),
        (48, 56, "dim cyan"),
    ]


def test_highlight_log_line_leaves_unrecognized_message_words_unstyled() -> None:
    line = "The INFO inside this message is intentional"

    highlighted = highlight_log_line(line)

    assert highlighted.plain == line
    assert [(span.start, span.end, span.style) for span in highlighted.spans] == [
        (4, 8, "green"),
    ]
