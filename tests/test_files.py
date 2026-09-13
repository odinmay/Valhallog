from pathlib import Path

from valhallog.sources.files import FileLogReader, is_text_log_file, scan_directory


def test_scan_directory_finds_sorted_text_files(tmp_path: Path) -> None:
    (tmp_path / "z-last.log").write_text("last")
    (tmp_path / "a-first.txt").write_text("first")
    (tmp_path / "extensionless").write_text("plain text")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "inside.log").write_text("inside")

    assert [path.name for path in scan_directory(tmp_path)] == [
        "a-first.txt",
        "extensionless",
        "z-last.log",
    ]
    assert [path.name for path in scan_directory(tmp_path, recursive=True)] == [
        "a-first.txt",
        "extensionless",
        "inside.log",
        "z-last.log",
    ]


def test_scan_directory_skips_binary_journal_and_compressed_files(tmp_path: Path) -> None:
    text_file = tmp_path / "readme"
    text_file.write_text("text")
    binary_file = tmp_path / "data"
    binary_file.write_bytes(b"header\x00binary")
    journal_file = tmp_path / "system.journal"
    journal_file.write_bytes(b"journal")
    compressed_file = tmp_path / "old.log.gz"
    compressed_file.write_bytes(b"compressed")

    assert is_text_log_file(text_file)
    assert not is_text_log_file(binary_file)
    assert not is_text_log_file(journal_file)
    assert not is_text_log_file(compressed_file)
    assert scan_directory(tmp_path) == [text_file]


def test_scan_directory_returns_empty_for_missing_directory(tmp_path: Path) -> None:
    assert scan_directory(tmp_path / "missing") == []


def test_file_log_reader_returns_only_recent_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "example.log"
    log_path.write_bytes(b"one\ntwo\nbad \xff\nfour\n")

    assert FileLogReader(log_path).read_recent_lines(2) == ["bad �", "four"]
