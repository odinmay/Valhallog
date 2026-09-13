import asyncio

import pytest

from valhallog.models import SourceConfig
from valhallog.sources.journal import JournalError, JournalReader, journalctl_args


@pytest.mark.parametrize(
    ("mode", "mode_args"),
    [
        ("system", ["--system"]),
        ("boot", ["--boot"]),
        ("kernel", ["--dmesg"]),
        ("errors", ["--priority=err..emerg"]),
    ],
)
def test_journalctl_args_map_modes(mode: str, mode_args: list[str]) -> None:
    source = SourceConfig(name="Journal", type="journal", mode=mode)

    assert journalctl_args(source) == [
        "journalctl",
        "--no-pager",
        "--output=short-iso",
        *mode_args,
    ]


def test_journalctl_args_add_native_level_filter() -> None:
    source = SourceConfig(name="System journal", type="journal", mode="system")
    errors = SourceConfig(name="Errors", type="journal", mode="errors")

    assert journalctl_args(source, "warning")[-1] == "--priority=warning..emerg"
    assert journalctl_args(source, "critical")[-1] == "--priority=crit..emerg"
    assert journalctl_args(errors, "critical")[-1] == "--priority=crit..emerg"


def test_journal_reader_builds_follow_command() -> None:
    source = SourceConfig(name="Current boot", type="journal", mode="boot")

    assert JournalReader(source).command(10, "error", follow=True) == [
        "journalctl",
        "--no-pager",
        "--output=short-iso",
        "--boot",
        "--priority=err..emerg",
        "--lines",
        "10",
        "--follow",
    ]


def test_journal_reader_streams_lines_without_a_shell(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    class FakeStream:
        def __init__(self, lines: list[bytes]):
            self._lines = iter(lines)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._lines)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeStderr:
        async def read(self) -> bytes:
            return b""

    class FakeProcess:
        stdout = FakeStream([b"first\n", b"second\r\n"])
        stderr = FakeStderr()
        returncode = 0

        async def wait(self) -> int:
            return self.returncode

    async def fake_create_subprocess_exec(*args, **kwargs):
        assert kwargs["stdout"] is asyncio.subprocess.PIPE
        assert kwargs["stderr"] is asyncio.subprocess.PIPE
        calls.append(tuple(args))
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    source = SourceConfig(name="Current boot", type="journal", mode="boot")

    lines = asyncio.run(JournalReader(source).read_lines(2))

    assert lines == ["first", "second"]
    assert calls == [
        (
            "journalctl",
            "--no-pager",
            "--output=short-iso",
            "--boot",
            "--lines",
            "2",
        )
    ]


def test_journal_reader_reports_stderr(monkeypatch) -> None:
    class FakeStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeStderr:
        async def read(self) -> bytes:
            return b"No journal files were found.\n"

    class FakeProcess:
        stdout = FakeStream()
        stderr = FakeStderr()
        returncode = 1

        async def wait(self) -> int:
            return self.returncode

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    source = SourceConfig(name="System journal", type="journal", mode="system")

    with pytest.raises(JournalError, match="No journal files were found"):
        asyncio.run(JournalReader(source).read_lines(5))


def test_journal_reader_terminates_process_when_cancelled(monkeypatch) -> None:
    class FakeStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.Event().wait()
            raise StopAsyncIteration

    class FakeStderr:
        async def read(self) -> bytes:
            return b""

    class FakeProcess:
        stdout = FakeStream()
        stderr = FakeStderr()
        returncode = None
        terminated = False

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15

        async def wait(self) -> int:
            return self.returncode

    process = FakeProcess()

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    source = SourceConfig(name="Current boot", type="journal", mode="boot")

    async def consume() -> None:
        async for _line in JournalReader(source).iter_lines(10, follow=True):
            pass

    async def run_test() -> None:
        task = asyncio.create_task(consume())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_test())
    assert process.terminated is True
