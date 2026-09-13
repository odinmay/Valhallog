"""Load and validate Valhallog's user-editable TOML configuration."""

from __future__ import annotations

import os
import pwd
import tomllib
from pathlib import Path
from typing import Any, Mapping

from .models import AppConfig, SourceConfig, ViewerConfig

CONFIG_FILENAME = "config.toml"
SUPPORTED_LEVELS = {"all", "debug", "info", "warning", "error", "critical"}
SUPPORTED_SOURCE_TYPES = {"directory", "journal"}
SUPPORTED_JOURNAL_MODES = {"system", "boot", "kernel", "errors"}


class ConfigError(ValueError):
    """A readable problem with the Valhallog configuration."""


def _environment(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def resolve_user_home(environ: Mapping[str, str] | None = None) -> Path:
    """Return the home directory of the user who launched Valhallog."""
    env = _environment(environ)
    sudo_user = env.get("SUDO_USER")
    if sudo_user:
        try:
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except KeyError as exc:
            raise ConfigError(f"Cannot find the invoking user: {sudo_user}") from exc

    home = env.get("HOME")
    return Path(home) if home else Path.home()


def _expand_user_path(value: str, user_home: Path) -> Path:
    if value == "~":
        return user_home
    if value.startswith("~/"):
        return user_home / value[2:]
    return Path(value).expanduser()


def resolve_config_path(environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the config path without accidentally using root's config."""
    env = _environment(environ)
    user_home = resolve_user_home(env)

    if env.get("SUDO_USER"):
        config_dir = user_home / ".config"
    elif env.get("XDG_CONFIG_HOME"):
        config_dir = _expand_user_path(env["XDG_CONFIG_HOME"], user_home)
    else:
        config_dir = user_home / ".config"

    return config_dir / "valhallog" / CONFIG_FILENAME


def _expect_table(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a TOML table")
    return value


def _read_positive_int(table: Mapping[str, Any], key: str, default: int) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"viewer.{key} must be a positive integer")
    return value


def _parse_viewer(raw_viewer: Any) -> ViewerConfig:
    viewer = _expect_table(raw_viewer, "[viewer]")
    initial_lines = _read_positive_int(viewer, "initial_lines", 1500)
    follow_poll_ms = _read_positive_int(viewer, "follow_poll_ms", 500)
    default_level = viewer.get("default_level", "all")
    if not isinstance(default_level, str) or default_level.lower() not in SUPPORTED_LEVELS:
        allowed = ", ".join(sorted(SUPPORTED_LEVELS))
        raise ConfigError(f"viewer.default_level must be one of: {allowed}")

    return ViewerConfig(
        initial_lines=initial_lines,
        follow_poll_ms=follow_poll_ms,
        default_level=default_level.lower(),
    )


def _parse_source(raw_source: Any, index: int, user_home: Path) -> SourceConfig:
    source = _expect_table(raw_source, f"sources[{index}]")
    name = source.get("name")
    source_type = source.get("type")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"sources[{index}].name must be a non-empty string")
    if not isinstance(source_type, str) or source_type not in SUPPORTED_SOURCE_TYPES:
        allowed = ", ".join(sorted(SUPPORTED_SOURCE_TYPES))
        raise ConfigError(f"sources[{index}].type must be one of: {allowed}")

    optional = source.get("optional", False)
    if not isinstance(optional, bool):
        raise ConfigError(f"sources[{index}].optional must be true or false")

    if source_type == "directory":
        raw_path = source.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ConfigError(f"sources[{index}].path is required for directory sources")
        recursive = source.get("recursive", False)
        if not isinstance(recursive, bool):
            raise ConfigError(f"sources[{index}].recursive must be true or false")
        return SourceConfig(
            name=name.strip(),
            type=source_type,
            path=_expand_user_path(raw_path, user_home),
            recursive=recursive,
            optional=optional,
        )

    mode = source.get("mode")
    if not isinstance(mode, str) or mode not in SUPPORTED_JOURNAL_MODES:
        allowed = ", ".join(sorted(SUPPORTED_JOURNAL_MODES))
        raise ConfigError(f"sources[{index}].mode must be one of: {allowed}")
    return SourceConfig(name=name.strip(), type=source_type, mode=mode, optional=optional)


def _parse_config(raw_config: Mapping[str, Any], config_path: Path, user_home: Path) -> AppConfig:
    version = raw_config.get("version", 1)
    if isinstance(version, bool) or version != 1:
        raise ConfigError("version must be 1")

    viewer = _parse_viewer(raw_config.get("viewer", {}))
    raw_sources = raw_config.get("sources", [])
    if not isinstance(raw_sources, list):
        raise ConfigError("sources must be an array of tables")

    sources = tuple(
        _parse_source(raw_source, index, user_home)
        for index, raw_source in enumerate(raw_sources)
    )
    return AppConfig(config_path=config_path, viewer=viewer, sources=sources)


def load_config(
    path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> AppConfig:
    """Read, validate, and return the user's configuration."""
    env = _environment(environ)
    config_path = Path(path) if path is not None else resolve_config_path(env)
    if not config_path.is_file():
        raise ConfigError(f"Configuration file not found: {config_path}")

    try:
        with config_path.open("rb") as config_file:
            raw_config = tomllib.load(config_file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {config_path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read {config_path}: {exc.strerror or exc}") from exc

    return _parse_config(raw_config, config_path, resolve_user_home(env))
