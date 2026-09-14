from pathlib import Path

from textual.widgets import Button, Footer, Header, Input, RichLog, Select, Static, Tree

from valhallog.app import (
    HelpScreen,
    TimeFilterScreen,
    ValhallogApp,
    _VALKNUT_BASE,
    _valknut_splash,
)
from valhallog.config import ConfigError
from valhallog.models import AppConfig, SourceConfig, ViewerConfig


def test_valknut_splash_preserves_artwork_spacing() -> None:
    base_lines = _VALKNUT_BASE.strip("\n").splitlines()
    base_width = max(map(len, base_lines))

    rendered_lines = _valknut_splash(0, 0).splitlines()

    assert rendered_lines == [
        line.ljust(base_width) for line in base_lines
    ]


def test_app_renders_hello_screen(monkeypatch) -> None:
    monkeypatch.setattr(
        "valhallog.app.load_config",
        lambda: (_ for _ in ()).throw(ConfigError("test configuration error")),
    )
    app = ValhallogApp()

    async def run_test() -> None:
        async with app.run_test() as pilot:
            assert app.query_one(Header)
            assert app.query_one(Footer)
            assert app.query_one("#source-tree", Tree)
            assert app.query_one("#log-viewer", RichLog)
            assert app.query_one("#level-select", Select).value == "all"
            assert "[v] All" in str(
                app.query_one("#level-select #label", Static).render()
            )
            splash = app.query_one("#splash", Static)
            assert "___      ___" in str(splash.render())
            assert splash.styles.display == "block"
            assert app.query_one("#source-tree", Tree).root.children

            focused_before_tab = app.focused
            await pilot.press("tab")
            assert focused_before_tab is not None
            assert app.focused is not focused_before_tab
            await pilot.press("?")
            assert isinstance(app.screen, HelpScreen)
            assert "Valhallog Help" in str(
                app.screen.query_one("#help-title", Static).render()
            )
            await pilot.press("escape")
            await pilot.press("q")

    import asyncio

    asyncio.run(run_test())


def test_app_displays_configured_sources(monkeypatch, tmp_path: Path) -> None:
    logs_path = tmp_path / "logs"
    logs_path.mkdir()
    (logs_path / "example.log").write_text("ERROR: example\n")
    monkeypatch.setattr(
        "valhallog.app.load_config",
        lambda: AppConfig(
            config_path=tmp_path / "config.toml",
            viewer=ViewerConfig(default_level="error", follow_poll_ms=10),
            sources=(
                SourceConfig(
                    name="Example Logs",
                    type="directory",
                    path=logs_path,
                ),
            ),
        ),
    )
    app = ValhallogApp()

    async def run_test() -> None:
        async with app.run_test() as pilot:
            source_tree = app.query_one("#source-tree", Tree)
            assert str(source_tree.root.children[0].label) == "Example Logs"
            assert str(source_tree.root.children[0].children[0].label) == "example.log"
            assert app.query_one("#level-select", Select).value == "error"

            source_tree.select_node(source_tree.root.children[0].children[0])
            await pilot.pause()
            log_viewer = app.query_one("#log-viewer", RichLog)
            assert app.query_one("#splash", Static).styles.display == "none"
            assert [line.text for line in log_viewer.lines] == ["ERROR: example"]
            assert str(app.query_one("#log-title", Static).render()) == "example.log"
            assert "Loaded 1 of 1 line" in str(
                app.query_one("#status", Static).render()
            )

            level_select = app.query_one("#level-select", Select)
            level_select.value = "critical"
            await pilot.pause()
            assert list(log_viewer.lines) == []
            level_select.value = "error"
            await pilot.pause()
            assert [line.text for line in log_viewer.lines] == ["ERROR: example"]

            await pilot.press("?")
            assert isinstance(app.screen, HelpScreen)
            assert "config.toml" in str(
                app.screen.query_one("#help-content", Static).render()
            )
            await pilot.press("escape")

            await pilot.press("f")
            assert app._following is True
            with (logs_path / "example.log").open("a") as log_file:
                log_file.write("ERROR: followed\n")
                log_file.flush()
            await pilot.pause(0.1)
            assert [line.text for line in log_viewer.lines] == [
                "ERROR: example",
                "ERROR: followed",
            ]

            await pilot.press("f")
            assert app._following is False
            with (logs_path / "example.log").open("a") as log_file:
                log_file.write("ERROR: ignored\n")
                log_file.flush()
            await pilot.pause(0.05)
            assert [line.text for line in log_viewer.lines] == [
                "ERROR: example",
                "ERROR: followed",
            ]
            await pilot.press("q")

    import asyncio

    asyncio.run(run_test())


def test_time_filter_menu_adjusts_and_clears_window(monkeypatch, tmp_path: Path) -> None:
    import asyncio

    monkeypatch.setattr(
        "valhallog.app.load_config",
        lambda: AppConfig(
            config_path=tmp_path / "config.toml",
            viewer=ViewerConfig(),
            sources=(),
        ),
    )
    app = ValhallogApp()

    async def run_test() -> None:
        async with app.run_test() as pilot:
            await pilot.click("#time-filter")
            assert isinstance(app.screen, TimeFilterScreen)
            window_input = app.screen.query_one("#time-window", Input)
            assert window_input.value == "5"

            await pilot.press("J")
            assert window_input.value == "4"
            await pilot.press("K")
            assert window_input.value == "5"
            await pilot.click("#time-plus")
            assert window_input.value == "6"

            app.screen.query_one("#time-date", Input).value = "2026-09-14"
            app.screen.query_one("#time-of-day", Input).value = "17:00:00"
            await pilot.click("#time-apply")
            assert app._active_time_window is not None
            assert app._active_time_window.minutes == 6
            assert str(app.query_one("#time-filter", Button).label) == "Time: ±6m"

            await pilot.click("#time-filter")
            await pilot.click("#time-clear")
            assert app._active_time_window is None
            await pilot.press("q")

    asyncio.run(run_test())


def test_time_filter_renders_full_file_and_restores_it_on_clear(
    monkeypatch, tmp_path: Path
) -> None:
    import asyncio

    logs_path = tmp_path / "logs"
    logs_path.mkdir()
    log_path = logs_path / "example.log"
    log_path.write_text(
        "2026-09-14T16:54:59 INFO: before\n"
        "2026-09-14T16:55:00 INFO: start\n"
        "2026-09-14T17:00:00 INFO: center\n"
        "2026-09-14T17:05:00 INFO: end\n"
        "2026-09-14T17:05:01 INFO: after\n"
        "plain text without a timestamp\n"
    )
    monkeypatch.setattr(
        "valhallog.app.load_config",
        lambda: AppConfig(
            config_path=tmp_path / "config.toml",
            viewer=ViewerConfig(initial_lines=1),
            sources=(SourceConfig(name="Logs", type="directory", path=logs_path),),
        ),
    )
    app = ValhallogApp()

    async def run_test() -> None:
        async with app.run_test() as pilot:
            source_tree = app.query_one("#source-tree", Tree)
            source_tree.select_node(source_tree.root.children[0].children[0])
            await pilot.pause()
            log_viewer = app.query_one("#log-viewer", RichLog)
            assert len(log_viewer.lines) == 6

            await pilot.click("#time-filter")
            app.screen.query_one("#time-date", Input).value = "2026-09-14"
            app.screen.query_one("#time-of-day", Input).value = "17:00:00"
            await pilot.click("#time-apply")
            assert [line.text for line in log_viewer.lines] == [
                "2026-09-14T16:55:00 INFO: start",
                "2026-09-14T17:00:00 INFO: center",
                "2026-09-14T17:05:00 INFO: end",
            ]

            await pilot.click("#time-filter")
            await pilot.click("#time-clear")
            assert len(log_viewer.lines) == 6
            await pilot.press("q")

    asyncio.run(run_test())


def test_app_displays_journal_source(monkeypatch, tmp_path: Path) -> None:
    import asyncio

    monkeypatch.setattr(
        "valhallog.app.load_config",
        lambda: AppConfig(
            config_path=tmp_path / "config.toml",
            viewer=ViewerConfig(initial_lines=25),
            sources=(
                SourceConfig(name="Current Boot", type="journal", mode="boot"),
            ),
        ),
    )

    class FakeJournalReader:
        def __init__(self, source: SourceConfig):
            self.source = source

        async def iter_lines(self, max_lines: int, level: str, follow: bool = False):
            assert max_lines == 25
            assert level == "all"
            if follow:
                yield "live journal line"
                await asyncio.Event().wait()
            else:
                yield "journal line one"
                yield "journal line two"

    monkeypatch.setattr("valhallog.app.JournalReader", FakeJournalReader)
    app = ValhallogApp()

    async def run_test() -> None:
        async with app.run_test() as pilot:
            source_tree = app.query_one("#source-tree", Tree)
            source_tree.select_node(source_tree.root.children[0])
            await pilot.pause()

            log_viewer = app.query_one("#log-viewer", RichLog)
            assert [line.text for line in log_viewer.lines] == [
                "journal line one",
                "journal line two",
            ]
            assert str(app.query_one("#log-title", Static).render()) == "Current Boot"
            assert "Loaded 2 journal line" in str(
                app.query_one("#status", Static).render()
            )

            await pilot.press("f")
            assert app._following is True
            await pilot.pause()
            assert "live journal line" in [line.text for line in log_viewer.lines]
            await pilot.press("f")
            assert app._following is False
            await pilot.press("q")

    asyncio.run(run_test())


def test_file_read_runs_off_the_ui_thread(monkeypatch, tmp_path: Path) -> None:
    import asyncio
    import threading

    logs_path = tmp_path / "logs"
    logs_path.mkdir()
    log_path = logs_path / "example.log"
    log_path.write_text("background read\n")
    monkeypatch.setattr(
        "valhallog.app.load_config",
        lambda: AppConfig(
            config_path=tmp_path / "config.toml",
            viewer=ViewerConfig(),
            sources=(SourceConfig(name="Logs", type="directory", path=logs_path),),
        ),
    )

    ui_thread_id = threading.get_ident()
    reader_thread_id = None

    class FakeFileLogReader:
        def __init__(self, path: Path):
            assert path == log_path

        def read_recent_lines(self, max_lines: int) -> list[str]:
            nonlocal reader_thread_id
            reader_thread_id = threading.get_ident()
            return ["background read"]

    monkeypatch.setattr("valhallog.app.FileLogReader", FakeFileLogReader)
    app = ValhallogApp()

    async def run_test() -> None:
        async with app.run_test() as pilot:
            source_tree = app.query_one("#source-tree", Tree)
            source_tree.select_node(source_tree.root.children[0].children[0])
            await pilot.pause()
            assert reader_thread_id is not None
            assert reader_thread_id != ui_thread_id
            await pilot.press("q")

    asyncio.run(run_test())


def test_app_reports_empty_directory(monkeypatch, tmp_path: Path) -> None:
    import asyncio

    empty_path = tmp_path / "empty"
    empty_path.mkdir()
    monkeypatch.setattr(
        "valhallog.app.load_config",
        lambda: AppConfig(
            config_path=tmp_path / "config.toml",
            viewer=ViewerConfig(),
            sources=(
                SourceConfig(name="Empty Logs", type="directory", path=empty_path),
            ),
        ),
    )
    app = ValhallogApp()

    async def run_test() -> None:
        async with app.run_test() as pilot:
            source_tree = app.query_one("#source-tree", Tree)
            assert "1 empty" in str(app.query_one("#status", Static).render())
            source_tree.select_node(source_tree.root.children[0])
            await pilot.pause()
            assert "No readable text logs" in str(
                app.query_one("#status", Static).render()
            )
            await pilot.press("q")

    asyncio.run(run_test())


def test_vim_navigation_scrolls_active_log_or_moves_sources(monkeypatch) -> None:
    import asyncio

    monkeypatch.setattr(
        "valhallog.app.load_config",
        lambda: AppConfig(
            config_path=Path("/tmp/config.toml"),
            viewer=ViewerConfig(),
            sources=(),
        ),
    )
    scroll_calls: list[str] = []
    page_calls: list[str] = []
    horizontal_calls: list[str] = []
    source_calls: list[str] = []
    tree_panel_calls: list[str] = []

    def record_scroll_up(self) -> None:
        scroll_calls.append("up")

    def record_scroll_down(self) -> None:
        scroll_calls.append("down")

    def record_scroll_left(self) -> None:
        horizontal_calls.append("left")

    def record_scroll_right(self) -> None:
        horizontal_calls.append("right")

    def record_page_up(self) -> None:
        page_calls.append("up")

    def record_page_down(self) -> None:
        page_calls.append("down")

    def record_source_up(self) -> None:
        source_calls.append("up")

    def record_source_down(self) -> None:
        source_calls.append("down")

    def record_tree_collapse(self) -> None:
        tree_panel_calls.append("collapse")

    def record_tree_expand(self) -> None:
        tree_panel_calls.append("expand")

    monkeypatch.setattr(RichLog, "action_scroll_up", record_scroll_up)
    monkeypatch.setattr(RichLog, "action_scroll_down", record_scroll_down)
    monkeypatch.setattr(RichLog, "action_scroll_left", record_scroll_left)
    monkeypatch.setattr(RichLog, "action_scroll_right", record_scroll_right)
    monkeypatch.setattr(RichLog, "action_page_up", record_page_up)
    monkeypatch.setattr(RichLog, "action_page_down", record_page_down)
    monkeypatch.setattr(Tree, "action_cursor_up", record_source_up)
    monkeypatch.setattr(Tree, "action_cursor_down", record_source_down)
    monkeypatch.setattr(ValhallogApp, "action_source_collapse", record_tree_collapse)
    monkeypatch.setattr(ValhallogApp, "action_source_expand_or_open", record_tree_expand)
    app = ValhallogApp()

    async def run_test() -> None:
        async with app.run_test() as pilot:
            log_viewer = app.query_one("#log-viewer", RichLog)
            source_tree = app.query_one("#source-tree", Tree)
            await pilot.press("H")
            assert app.focused is source_tree
            await pilot.press("L")
            assert app.focused is log_viewer

            source_tree.focus()
            await pilot.press("h", "l")
            assert tree_panel_calls == ["collapse", "expand"]

            await pilot.press("v")
            level_select = app.query_one("#level-select", Select)
            assert app.focused is level_select.query_one("SelectOverlay")
            await pilot.pause()
            footer = app.query_one(Footer)
            footer_actions = {
                child.action for child in footer.query("FooterKey")
            }
            assert {"cursor_down", "cursor_up", "select", "dismiss"} <= footer_actions
            assert "increase_source_panel" not in footer_actions
            assert "decrease_source_panel" not in footer_actions
            assert "command_palette" not in footer_actions
            await pilot.press("h")
            await pilot.pause()
            assert level_select.expanded is False
            assert app.focused is level_select

            await pilot.press("v")
            await pilot.pause()
            assert app.focused is level_select.query_one("SelectOverlay")
            await pilot.press("j")
            assert level_select.query_one("SelectOverlay").highlighted == 1
            await pilot.press("k")
            assert level_select.query_one("SelectOverlay").highlighted == 0
            await pilot.press("j", "l")
            await pilot.pause()
            assert level_select.value == "debug"
            assert level_select.expanded is False

            log_viewer.focus()
            await pilot.pause()
            footer_actions = {
                child.action for child in footer.query("FooterKey")
            }
            assert "add_source" not in footer_actions
            assert "rename_source" not in footer_actions
            assert "log_page_up" in footer_actions
            assert "log_page_down" in footer_actions
            await pilot.press("k", "j")
            assert scroll_calls == ["up", "down"]
            assert source_calls == []
            await pilot.press("h", "l")
            assert horizontal_calls == ["left", "right"]
            await pilot.press("K", "J")
            assert page_calls == ["up", "down"]

            source_tree.focus()
            await pilot.pause()
            footer_actions = {
                child.action for child in footer.query("FooterKey")
            }
            assert "log_page_up" not in footer_actions
            assert "log_page_down" not in footer_actions
            assert "add_source" in footer_actions
            assert "rename_source" in footer_actions
            await pilot.press("k", "j")
            assert source_calls == ["up", "down"]
            await pilot.press("K", "J")
            assert page_calls == ["up", "down"]
            await pilot.press("+")
            assert app._source_width_percent == 25
            await pilot.press("=")
            assert app._source_width_percent == 30
            await pilot.press("-")
            assert app._source_width_percent == 25
            await pilot.press("q")

    asyncio.run(run_test())
