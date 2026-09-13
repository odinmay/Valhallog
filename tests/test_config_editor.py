from pathlib import Path

import pytest
import tomlkit

from valhallog.config import load_config
from valhallog.config_editor import (
    SourceAlreadyExistsError,
    add_directory_source,
    rename_source,
)
from valhallog.models import SourceConfig


def _write_config(path: Path, source_block: str = "") -> None:
    path.write_text(
        """# Keep this comment when sources are added.
version = 1

[viewer]
default_level = "all"
"""
        + source_block,
        encoding="utf-8",
    )


def test_add_directory_source_preserves_toml_and_uses_home_path(tmp_path: Path) -> None:
    home = tmp_path / "home"
    selected = home / "My Logs"
    selected.mkdir(parents=True)
    config_path = tmp_path / "config.toml"
    _write_config(config_path)

    source = add_directory_source(
        config_path,
        selected,
        recursive=True,
        user_home=home,
        name="Application logs",
    )

    assert source.name == "Application logs"
    assert source.path == selected.resolve()
    assert source.recursive is True
    content = config_path.read_text(encoding="utf-8")
    assert "# Keep this comment" in content
    assert 'name = "Application logs"' in content
    assert 'path = "~/My Logs"' in content
    assert load_config(config_path, environ={"HOME": str(home)}).sources == (source,)


def test_add_directory_source_rejects_duplicate_resolved_path(tmp_path: Path) -> None:
    home = tmp_path / "home"
    selected = home / "logs"
    selected.mkdir(parents=True)
    config_path = tmp_path / "config.toml"
    _write_config(
        config_path,
        """
[[sources]]
name = "Existing logs"
type = "directory"
path = "~/logs"
""",
    )

    with pytest.raises(SourceAlreadyExistsError):
        add_directory_source(
            config_path,
            selected,
            recursive=False,
            user_home=home,
        )


def test_added_toml_is_valid_tomlkit_document(tmp_path: Path) -> None:
    selected = tmp_path / "logs"
    selected.mkdir()
    config_path = tmp_path / "config.toml"
    _write_config(config_path)

    add_directory_source(
        config_path,
        selected,
        recursive=False,
        user_home=tmp_path,
    )

    document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    assert document["sources"][0]["type"] == "directory"


def test_rename_source_preserves_toml_and_updates_name(tmp_path: Path) -> None:
    home = tmp_path / "home"
    selected = home / "logs"
    selected.mkdir(parents=True)
    config_path = tmp_path / "config.toml"
    _write_config(
        config_path,
        """
[[sources]]
name = "logs"
type = "directory"
path = "~/logs"
recursive = true
""",
    )
    source = SourceConfig(
        name="logs",
        type="directory",
        path=selected,
        recursive=True,
    )

    renamed = rename_source(
        config_path,
        source,
        new_name="Application logs",
        user_home=home,
    )

    assert renamed.name == "Application logs"
    assert '# Keep this comment' in config_path.read_text(encoding="utf-8")
    assert 'name = "Application logs"' in config_path.read_text(encoding="utf-8")
    assert load_config(config_path, environ={"HOME": str(home)}).sources == (renamed,)
