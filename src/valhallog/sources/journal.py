"""Read virtual journal sources through the ``journalctl`` command."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from ..filters import normalize_level
from ..models import SourceConfig
from ..time_filters import TimeWindow


JOURNALCTL = "journalctl"
_BASE_ARGS = [JOURNALCTL, "--no-pager", "--output=short-iso"]
_MODE_ARGS = {
    "system": ["--system"],
    "boot": ["--boot"],
    "kernel": ["--dmesg"],
    "errors": [],
}
_LEVEL_RANK = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}
_JOURNAL_PRIORITIES = {
    "debug": "debug",
    "info": "info",
    "warning": "warning",
    "error": "err",
    "critical": "crit",
}


class JournalError(RuntimeError):
    """A journal command could not produce a usable result."""


def journalctl_args(
    source: SourceConfig,
    level: str = "all",
    time_window: TimeWindow | None = None,
) -> list[str]:
    """Return the safe, shell-free ``journalctl`` arguments for a source."""
    if source.type != "journal":
        raise ValueError("journalctl_args requires a journal source")
    if source.mode not in _MODE_ARGS:
        raise ValueError(f"unsupported journal mode: {source.mode!r}")
    normalized_level = normalize_level(level)
    args = [*_BASE_ARGS, *_MODE_ARGS[source.mode]]

    threshold = _LEVEL_RANK.get(normalized_level, -1)
    if source.mode == "errors":
        threshold = max(threshold, _LEVEL_RANK["error"])
    if threshold >= 0:
        selected = next(
            name for name, rank in _LEVEL_RANK.items() if rank == threshold
        )
        args.append(f"--priority={_JOURNAL_PRIORITIES[selected]}..emerg")
    if time_window is not None:
        args.extend(
            [
                f"--since={time_window.start.isoformat()}",
                f"--until={time_window.end.isoformat()}",
            ]
        )
    return args


class JournalReader:
    """Stream recent lines from one configured virtual journal source."""

    def __init__(self, source: SourceConfig):
        self.source = source

    def command(
        self,
        max_lines: int | None,
        level: str = "all",
        follow: bool = False,
        time_window: TimeWindow | None = None,
    ) -> list[str]:
        """Build a bounded command for the configured source."""
        if max_lines is not None and max_lines <= 0:
            raise ValueError("max_lines must be positive")
        command = [
            *journalctl_args(self.source, level, time_window),
        ]
        if time_window is None:
            if max_lines is None:
                raise ValueError("max_lines is required without a time window")
            command.extend(["--lines", str(max_lines)])
        else:
            command.append("--lines=all")
        if follow:
            command.append("--follow")
        return command

    async def iter_lines(
        self,
        max_lines: int | None,
        level: str = "all",
        follow: bool = False,
        time_window: TimeWindow | None = None,
    ) -> AsyncIterator[str]:
        """Yield decoded journal lines as ``journalctl`` writes them."""
        process = await asyncio.create_subprocess_exec(
            *self.command(max_lines, level, follow, time_window),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdout is None or process.stderr is None:
            raise JournalError("journalctl did not provide stdout and stderr")

        try:
            async for raw_line in process.stdout:
                yield raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

            stderr = await process.stderr.read()
            returncode = await process.wait()
            if returncode != 0:
                detail = stderr.decode("utf-8", errors="replace").strip()
                message = detail or f"exited with status {returncode}"
                raise JournalError(f"Could not read {self.source.name}: {message}")
        except asyncio.CancelledError:
            if process.returncode is None:
                process.terminate()
                await process.wait()
            raise

    async def read_lines(
        self,
        max_lines: int | None,
        level: str = "all",
        follow: bool = False,
        time_window: TimeWindow | None = None,
    ) -> list[str]:
        """Collect recent lines for callers that do not need streaming."""
        return [
            line
            async for line in self.iter_lines(
                max_lines, level, follow, time_window
            )
        ]
