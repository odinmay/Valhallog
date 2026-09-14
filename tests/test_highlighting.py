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


def test_highlight_log_line_styles_common_log_entities() -> None:
    line = (
        "INFO sshd.service pid=123 from 192.168.1.10 port=22 "
        "path=/var/log/auth.log dev=/dev/sda1 interface=enp0s3 "
        "mac=aa:bb:cc:dd:ee:ff https://example.com."
    )

    highlighted = highlight_log_line(line)
    spans = {
        (line[span.start:span.end], span.style)
        for span in highlighted.spans
    }

    assert ("sshd.service", "magenta") in spans
    assert ("pid=123", "bright_magenta") in spans
    assert ("192.168.1.10", "bright_cyan") in spans
    assert ("port=22", "yellow") in spans
    assert ("/var/log/auth.log", "blue") in spans
    assert ("/dev/sda1", "bold yellow") in spans
    assert ("enp0s3", "bold yellow") in spans
    assert ("aa:bb:cc:dd:ee:ff", "bright_green") in spans
    assert ("https://example.com", "underline blue") in spans
    assert ("//example.com", "blue") not in spans


def test_highlight_log_line_supports_ipv6_and_bracketed_process_ids() -> None:
    line = "kernel[456]: connected to fe80::1 on nvme0n1p2"

    highlighted = highlight_log_line(line)
    spans = {
        (line[span.start:span.end], span.style)
        for span in highlighted.spans
    }

    assert ("[456]", "bright_magenta") in spans
    assert ("fe80::1", "bright_cyan") in spans
    assert ("nvme0n1p2", "bold yellow") in spans
