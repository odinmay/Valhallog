"""Data structures used by Valhallog configuration."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ViewerConfig:
    """Settings that control the log viewer."""

    initial_lines: int = 1500
    follow_poll_ms: int = 500
    default_level: str = "all"


@dataclass(frozen=True)
class SourceConfig:
    """One configured directory or virtual journal source."""

    name: str
    type: str
    path: Path | None = None
    recursive: bool = False
    mode: str | None = None
    optional: bool = False


@dataclass(frozen=True)
class AppConfig:
    """The complete validated Valhallog configuration."""

    config_path: Path
    viewer: ViewerConfig
    sources: tuple[SourceConfig, ...]
