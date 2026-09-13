from pathlib import Path
from types import SimpleNamespace

import pytest

from valhallog.config import ConfigError, load_config, resolve_config_path


def test_resolve_config_path_uses_xdg_config_home() -> None:
    path = resolve_config_path(
        {"HOME": "/home/alice", "XDG_CONFIG_HOME": "/tmp/alice-config"}
    )

    assert path == Path("/tmp/alice-config/valhallog/config.toml")


def test_resolve_config_path_uses_invoking_user_when_sudo(monkeypatch) -> None:
    monkeypatch.setattr(
        "valhallog.config.pwd.getpwnam",
        lambda username: SimpleNamespace(pw_dir="/home/alice"),
    )

    path = resolve_config_path(
        {
            "HOME": "/root",
            "XDG_CONFIG_HOME": "/root/.config",
            "SUDO_USER": "alice",
        }
    )

    assert path == Path("/home/alice/.config/valhallog/config.toml")


def test_load_config_parses_sources_and_expands_user_path(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
version = 1

[viewer]
initial_lines = 25
follow_poll_ms = 100
default_level = "warning"

[[sources]]
name = "Logs"
type = "directory"
path = "~/logs"
recursive = true

[[sources]]
name = "Current Boot"
type = "journal"
mode = "boot"
""".strip()
    )

    config = load_config(config_path, environ={"HOME": "/home/alice"})

    assert config.config_path == config_path
    assert config.viewer.initial_lines == 25
    assert config.viewer.default_level == "warning"
    assert config.sources[0].path == Path("/home/alice/logs")
    assert config.sources[1].mode == "boot"


def test_load_config_rejects_invalid_source(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[[sources]]
name = "Broken"
type = "directory"
""".strip()
    )

    with pytest.raises(ConfigError, match="path is required"):
        load_config(config_path, environ={"HOME": "/home/alice"})


def test_load_config_reports_missing_file(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.toml"

    with pytest.raises(ConfigError, match="Configuration file not found"):
        load_config(config_path)


def test_load_config_reports_invalid_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[viewer\n")

    with pytest.raises(ConfigError, match="Invalid TOML"):
        load_config(config_path)


def test_load_config_rejects_invalid_default_level(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[viewer]
default_level = "verbose"
""".strip()
    )

    with pytest.raises(ConfigError, match="viewer.default_level"):
        load_config(config_path)
