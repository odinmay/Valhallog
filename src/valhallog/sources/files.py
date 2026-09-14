"""Find safe, text-like files under a configured directory."""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Iterator
from pathlib import Path

TEXT_SUFFIXES = {".log", ".out", ".err", ".txt"}
SKIPPED_SUFFIXES = (".journal", ".journal~", ".gz", ".xz", ".zst")
SAMPLE_SIZE = 4096


class FileLogReader:
    """Read the most recent lines from one text log file."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def read_recent_lines(self, max_lines: int | None) -> list[str]:
        """Read lines, optionally keeping only the requested tail."""
        if max_lines is not None and max_lines <= 0:
            raise ValueError("max_lines must be positive")

        lines: deque[str] = deque(maxlen=max_lines)
        with self.path.open("r", encoding="utf-8", errors="replace") as file:
            for line in file:
                lines.append(line.rstrip("\r\n"))
        return list(lines)

    def iter_line_batches(
        self, batch_size: int = 500
    ) -> Iterator[tuple[list[str], int]]:
        """Yield decoded lines in UI-sized batches with the byte offset read."""
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        batch: list[str] = []
        with self.path.open("r", encoding="utf-8", errors="replace") as file:
            while True:
                line = file.readline()
                if not line:
                    break
                batch.append(line.rstrip("\r\n"))
                if len(batch) >= batch_size:
                    yield batch, file.tell()
                    batch = []
            if batch:
                yield batch, file.buffer.tell()


def _is_skipped(path: Path) -> bool:
    return path.name.casefold().endswith(SKIPPED_SUFFIXES)


def _looks_like_text(path: Path) -> bool:
    """Use a small byte sample to reject obvious binary files."""
    try:
        with path.open("rb") as file:
            sample = file.read(SAMPLE_SIZE)
    except OSError:
        return False

    if not sample:
        return True
    if b"\x00" in sample:
        return False

    control_bytes = sum(
        byte < 32 and byte not in {9, 10, 13}
        for byte in sample
    )
    return control_bytes / len(sample) < 0.10


def is_text_log_file(path: Path) -> bool:
    """Return whether ``path`` is a safe candidate for the source tree."""
    if _is_skipped(path) or path.is_symlink() or not path.is_file():
        return False

    if path.suffix.casefold() in TEXT_SUFFIXES:
        return True
    if path.suffix:
        return False
    return _looks_like_text(path)


def _iter_candidates(directory: Path, recursive: bool):
    if recursive:
        for current, _directories, filenames in os.walk(
            directory,
            topdown=True,
            followlinks=False,
            onerror=lambda _error: None,
        ):
            for filename in filenames:
                yield Path(current) / filename
        return

    try:
        yield from directory.iterdir()
    except OSError:
        return


def scan_directory(directory: Path, recursive: bool = False) -> list[Path]:
    """Return eligible files in predictable relative-path order."""
    directory = Path(directory)
    if not directory.is_dir():
        return []

    files = [
        candidate
        for candidate in _iter_candidates(directory, recursive)
        if is_text_log_file(candidate)
    ]
    return sorted(
        files,
        key=lambda path: str(path.relative_to(directory)).casefold(),
    )
