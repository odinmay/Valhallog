"""Small, safe edits to the user configuration."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

import tomlkit

from .models import SourceConfig


class SourceAlreadyExistsError(ValueError):
    """Raised when a directory is already configured as a source."""


def _resolve_stored_path(value: str, user_home: Path) -> Path:
    """Resolve a TOML path using the same home directory as config loading."""
    if value == "~":
        return user_home.resolve(strict=False)
    if value.startswith("~/"):
        return (user_home / value[2:]).resolve(strict=False)
    return Path(value).expanduser().resolve(strict=False)


def _display_path(path: Path, user_home: Path) -> str:
    """Use a portable home-relative path when the folder is under the home."""
    try:
        relative = path.relative_to(user_home)
    except ValueError:
        return str(path)
    return "~" if not relative.parts else f"~/{relative.as_posix()}"


def _write_atomically(config_path: Path, content: str) -> None:
    """Replace the config file only after the complete new document is ready."""
    mode = stat.S_IMODE(config_path.stat().st_mode)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, config_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def add_directory_source(
    config_path: Path,
    source_path: Path,
    *,
    recursive: bool,
    user_home: Path,
    name: str | None = None,
) -> SourceConfig:
    """Append one directory source to an existing TOML config.

    The path is compared after resolution so the same directory cannot be
    added twice under two different spellings. The returned source is ready to
    add to the in-memory application configuration.
    """
    config_path = Path(config_path)
    user_home = Path(user_home).resolve(strict=False)
    source_path = Path(source_path).expanduser().resolve(strict=False)
    if not source_path.is_dir():
        raise ValueError(f"Selected folder is not readable: {source_path}")

    document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    sources = document.get("sources")
    if sources is None:
        sources = tomlkit.aot()
        document.add("sources", sources)

    for source in sources:
        if source.get("type") != "directory":
            continue
        stored_path = source.get("path")
        if isinstance(stored_path, str) and _resolve_stored_path(
            stored_path, user_home
        ) == source_path:
            raise SourceAlreadyExistsError(
                f"The folder is already configured: {source_path}"
            )

    source_name = (name or source_path.name or str(source_path)).strip()
    if not source_name:
        raise ValueError("Source name cannot be empty")
    source_table = tomlkit.table()
    source_table.add("name", source_name)
    source_table.add("type", "directory")
    source_table.add("path", _display_path(source_path, user_home))
    source_table.add("recursive", recursive)
    sources.append(source_table)
    _write_atomically(config_path, document.as_string())

    return SourceConfig(
        name=source_name,
        type="directory",
        path=source_path,
        recursive=recursive,
    )


def _matches_source(
    raw_source, source: SourceConfig, user_home: Path
) -> bool:
    """Identify the TOML table represented by an in-memory source."""
    if raw_source.get("type") != source.type:
        return False
    if raw_source.get("name") != source.name:
        return False
    if source.type == "directory":
        stored_path = raw_source.get("path")
        return (
            source.path is not None
            and isinstance(stored_path, str)
            and _resolve_stored_path(stored_path, user_home)
            == source.path.resolve(strict=False)
        )
    return raw_source.get("mode") == source.mode


def rename_source(
    config_path: Path,
    source: SourceConfig,
    *,
    new_name: str,
    user_home: Path,
) -> SourceConfig:
    """Rename one configured source while preserving the TOML document."""
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("Source name cannot be empty")

    config_path = Path(config_path)
    user_home = Path(user_home).resolve(strict=False)
    document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    sources = document.get("sources")
    if sources is None:
        raise ValueError(f"Source not found: {source.name}")

    for raw_source in sources:
        if _matches_source(raw_source, source, user_home):
            raw_source["name"] = new_name
            _write_atomically(config_path, document.as_string())
            return SourceConfig(
                name=new_name,
                type=source.type,
                path=source.path,
                recursive=source.recursive,
                mode=source.mode,
                optional=source.optional,
            )

    raise ValueError(f"Source not found: {source.name}")
