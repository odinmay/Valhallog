from pathlib import Path

from valhallog.widgets.source_picker import FoldersOnlyTree


def test_source_picker_keeps_hidden_directories_and_excludes_files(tmp_path: Path) -> None:
    hidden = tmp_path / ".hidden"
    visible = tmp_path / "visible"
    file_path = tmp_path / "not-a-folder.log"
    hidden.mkdir()
    visible.mkdir()
    file_path.write_text("log\n", encoding="utf-8")

    assert FoldersOnlyTree.filter_paths([file_path, hidden, visible]) == [hidden, visible]
