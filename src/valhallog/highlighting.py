"""Rich text highlighting for log lines."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterator

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

_URL_PATTERN = re.compile(r"\b(?:https?://|ftp://|www\.)[^\s<>()[\]{}]+", re.I)
_NETWORK_CANDIDATE_PATTERN = re.compile(r"(?<![\w])(?:[\da-fA-F:.]){2,}(?![\w])")
_MAC_PATTERN = re.compile(
    r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b"
    r"|\b[0-9A-Fa-f]{2}(?:-[0-9A-Fa-f]{2}){5}\b"
)
_PROCESS_ID_PATTERN = re.compile(
    r"\b(?:pid|ppid|tid|tgid|process(?:\s+id)?)\s*[=:]?\s*#?\d+\b"
    r"|(?<!\d)\[\d{1,8}\](?!\w)",
    re.IGNORECASE,
)
_PATH_PATTERN = re.compile(
    r"(?<![:\w])(?:~|/|\./|\.\./)[^\s\"'<>()[\]{}]+"
)
_SERVICE_PATTERN = re.compile(
    r"\b[\w@%:.+-]+\.(?:service|socket|target|timer|mount|path|scope|slice)\b",
    re.IGNORECASE,
)
_DEVICE_PATTERN = re.compile(
    r"(?<![\w])/(?:dev|sys|proc)/[^\s\"'<>()[\]{}]+"
    r"|\b(?:eth\d+|en[opsx]\w+|wl\w+|lo|br\w+|virbr\w+|"
    r"docker\w*|veth\w+|bond\d+|tun\d+|tap\d+|"
    r"nvme\d+n\d+(?:p\d+)?|sd[a-z]+\d*|vd[a-z]+\d*|xvd[a-z]+\d*|"
    r"tty(?:S|USB|ACM)\d+|i2c-\d+|card\d+)\b",
    re.IGNORECASE,
)
_PORT_PATTERN = re.compile(
    r"\b(?:port|sport|dport|src_port|dst_port)\s*[=:]\s*\d{1,5}\b",
    re.IGNORECASE,
)
_FIELD_PATTERN = re.compile(
    r"\b(?:user|uid|gid|group|host|hostname|unit|comm|exe|cmd|exit|status|"
    r"errno|signal|fd|protocol|proto|interface|device|mode|action|result)\s*[=:]",
    re.IGNORECASE,
)
_ENTITY_STYLES = {
    "url": "underline blue",
    "ip": "bright_cyan",
    "mac": "bright_green",
    "pid": "bright_magenta",
    "path": "blue",
    "service": "magenta",
    "device": "bold yellow",
    "port": "yellow",
    "field": "bold white",
}


def _trim_punctuation(start: int, end: int, line: str) -> tuple[int, int]:
    """Exclude sentence punctuation from path and URL highlights."""
    while end > start and line[end - 1] in ",.;:!?":
        end -= 1
    return start, end


def _network_matches(line: str) -> Iterator[re.Match[str]]:
    """Yield only network-looking tokens that ``ipaddress`` accepts."""
    for match in _NETWORK_CANDIDATE_PATTERN.finditer(line):
        candidate = match.group()
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        yield match


def highlight_log_line(line: str) -> Text:
    """Style timestamps, severity, and common log entities."""
    highlighted = Text(line)

    for match in TIMESTAMP_PATTERN.finditer(line):
        highlighted.stylize("dim cyan", match.start(), match.end())

    for match in _SEVERITY_TOKEN_PATTERN.finditer(line):
        level = classify_token(match.group())
        if level is not None:
            highlighted.stylize(
                _SEVERITY_STYLES[level], match.start(), match.end()
            )

    for match in _URL_PATTERN.finditer(line):
        start, end = _trim_punctuation(match.start(), match.end(), line)
        highlighted.stylize(_ENTITY_STYLES["url"], start, end)

    for match in _network_matches(line):
        highlighted.stylize(_ENTITY_STYLES["ip"], match.start(), match.end())

    for match in _MAC_PATTERN.finditer(line):
        highlighted.stylize(_ENTITY_STYLES["mac"], match.start(), match.end())

    for match in _PROCESS_ID_PATTERN.finditer(line):
        highlighted.stylize(_ENTITY_STYLES["pid"], match.start(), match.end())

    for match in _PATH_PATTERN.finditer(line):
        start, end = _trim_punctuation(match.start(), match.end(), line)
        highlighted.stylize(_ENTITY_STYLES["path"], start, end)

    for match in _SERVICE_PATTERN.finditer(line):
        highlighted.stylize(_ENTITY_STYLES["service"], match.start(), match.end())

    for match in _DEVICE_PATTERN.finditer(line):
        start, end = _trim_punctuation(match.start(), match.end(), line)
        highlighted.stylize(_ENTITY_STYLES["device"], start, end)

    for match in _PORT_PATTERN.finditer(line):
        highlighted.stylize(_ENTITY_STYLES["port"], match.start(), match.end())

    for match in _FIELD_PATTERN.finditer(line):
        highlighted.stylize(_ENTITY_STYLES["field"], match.start(), match.end())

    return highlighted
