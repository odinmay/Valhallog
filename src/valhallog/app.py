"""The runnable Valhallog application."""

import asyncio
from pathlib import Path
from threading import Thread

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, RichLog, Select, Static, Tree
from textual.worker import Worker, WorkerState, get_current_worker

from .config import ConfigError, load_config
from .filters import filter_lines, normalize_level, should_show
from .models import AppConfig, SourceConfig
from .sources.files import FileLogReader, scan_directory
from .sources.journal import JournalError, JournalReader


VIEWER_HISTORY_LIMIT = 2000


class HelpScreen(ModalScreen[None]):
    """A small keyboard reference and configuration reminder."""

    BINDINGS = [
        Binding("escape", "close_help", "Close", show=False),
        Binding("q", "close_help", "Close", show=False),
    ]

    def __init__(self, config_path: Path | None):
        super().__init__()
        self.config_path = config_path

    def compose(self) -> ComposeResult:
        config_text = str(self.config_path) if self.config_path else "not loaded"
        yield Vertical(
            Static("Valhallog Help", id="help-title"),
            Static(
                "q  Quit\n"
                "f  Toggle follow for the selected source\n"
                "Tab  Move focus\n"
                "?  Open this help\n"
                "Escape  Close this help\n\n"
                "Choose a source from the tree. Use the level selector to filter\n"
                "plain files or set the native journal priority.\n\n"
                f"Config: {config_text}",
                id="help-content",
            ),
            Button("Close", id="close-help"),
            id="help-dialog",
        )

    def action_close_help(self) -> None:
        """Close the help screen."""
        self.dismiss()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Close the modal when its button is pressed."""
        if event.button.id == "close-help":
            self.dismiss()


class ValhallogApp(App[None]):
    """A minimal Textual app shell for Valhallog."""

    TITLE = "Valhallog"
    CSS_PATH = "app.tcss"
    config: AppConfig | None = None
    _selected_path: Path | None = None
    _selected_source: SourceConfig | None = None
    _active_level = "all"
    _raw_lines: list[str] | None = None
    _following = False
    _follow_worker: Worker[None] | None = None
    _journal_follow_worker: Worker[None] | None = None
    _file_worker: Worker[list[str]] | None = None
    _journal_worker: Worker[None] | None = None

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("?", "show_help", "Help"),
        Binding("tab", "focus_next", "Focus next"),
        Binding("f", "toggle_follow", "Follow"),
    ]

    def compose(self) -> ComposeResult:
        """Describe the widgets that make up the first screen."""
        yield Header()
        yield Vertical(
            Horizontal(
                Select(
                    [
                        ("All", "all"),
                        ("Debug", "debug"),
                        ("Info", "info"),
                        ("Warning", "warning"),
                        ("Error", "error"),
                        ("Critical", "critical"),
                    ],
                    value="all",
                    id="level-select",
                ),
                Static("Source: none | Level: ALL", id="status"),
                id="controls",
            ),
            Horizontal(
                Vertical(
                    Static("Sources", classes="pane-title"),
                    Tree("Sources", id="source-tree"),
                    id="source-pane",
                ),
                Vertical(
                    Static("Hello Valhallog", id="log-title", classes="pane-title"),
                    RichLog(
                        id="log-viewer",
                        highlight=False,
                        markup=False,
                        max_lines=VIEWER_HISTORY_LIMIT,
                    ),
                    id="log-pane",
                ),
                id="main-content",
            ),
            id="body",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load configured source names while keeping the UI responsive."""
        self._selected_path = None
        self._selected_source = None
        self._active_level = "all"
        self._raw_lines = None
        self._following = False
        self._follow_worker = None
        self._journal_follow_worker = None
        self._file_worker = None
        self._journal_worker = None
        source_tree = self.query_one("#source-tree", Tree)
        status = self.query_one("#status", Static)

        try:
            config = load_config()
        except ConfigError as exc:
            source_tree.root.add("No configured sources")
            status.update(f"Config error: {exc}")
        else:
            self.config = config
            self._active_level = config.viewer.default_level
            self.query_one("#level-select", Select).value = config.viewer.default_level
            file_count = 0
            missing_count = 0
            empty_count = 0
            for source in config.sources:
                if source.type == "directory":
                    if source.path is None or not source.path.is_dir():
                        missing_count += 1
                        missing_label = (
                            " (optional, missing)" if source.optional else " (missing)"
                        )
                        source_tree.root.add(
                            source.name + missing_label,
                            data=source,
                            allow_expand=False,
                        )
                        continue

                    source_node = source_tree.root.add(
                        source.name,
                        data=source,
                        expand=True,
                    )
                    files = scan_directory(source.path, source.recursive)
                    file_count += len(files)
                    if not files:
                        empty_count += 1
                    for file_path in files:
                        source_node.add(
                            str(file_path.relative_to(source.path)),
                            data=file_path,
                            allow_expand=False,
                        )
                else:
                    source_tree.root.add(source.name, data=source, allow_expand=False)

            source_tree.root.expand()
            missing_text = f"; {missing_count} missing" if missing_count else ""
            empty_text = f"; {empty_count} empty" if empty_count else ""
            if config.sources:
                status.update(
                    f"Loaded {len(config.sources)} source(s), {file_count} file(s)"
                    f"{missing_text}{empty_text}"
                )
            else:
                status.update("No configured sources")

        log_viewer = self.query_one("#log-viewer", RichLog)
        log_viewer.write("Hello Valhallog")
        log_viewer.write("The log viewer will grow here.")

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Load the selected file or virtual journal source."""
        config = self.config
        if not isinstance(config, AppConfig):
            return
        self._stop_readers()
        self._raw_lines = None

        if isinstance(event.node.data, Path):
            self._selected_path = event.node.data
            self._selected_source = None
            self._start_file_load(event.node.data, config.viewer.initial_lines)
        elif isinstance(event.node.data, SourceConfig) and event.node.data.type == "journal":
            self._selected_path = None
            self._selected_source = event.node.data
            self._start_journal_load(event.node.data, config.viewer.initial_lines)
        elif isinstance(event.node.data, SourceConfig):
            self._selected_path = None
            self._selected_source = None
            self.query_one("#log-title", Static).update(event.node.data.name)
            self.query_one("#status", Static).update(
                f"No readable text logs found in {event.node.data.name}"
            )
        else:
            self._selected_path = None
            self._selected_source = None

    def _start_file_load(self, path: Path, max_lines: int) -> None:
        """Start a background read for the selected file."""
        log_viewer = self.query_one("#log-viewer", RichLog)
        log_title = self.query_one("#log-title", Static)
        status = self.query_one("#status", Static)
        log_title.update(path.name)
        log_viewer.clear()
        status.update(f"Loading {path}...")
        self._raw_lines = []
        self._file_worker = self.run_worker(
            self._read_file_worker(path, max_lines),
            name="load-file",
            group="file-reader",
            exclusive=True,
            exit_on_error=False,
        )

    async def _read_file_worker(self, path: Path, max_lines: int) -> list[str]:
        """Read a file off the UI loop and return its lines to the worker."""
        loop = asyncio.get_running_loop()
        result: asyncio.Future[list[str]] = loop.create_future()

        def publish(callback) -> None:
            """Publish a reader result unless the app loop is already closed."""
            try:
                loop.call_soon_threadsafe(callback)
            except RuntimeError:
                pass

        def read_file() -> None:
            try:
                lines = FileLogReader(path).read_recent_lines(max_lines)
            except Exception as error:
                publish(
                    lambda error=error: not result.done()
                    and result.set_exception(error)
                )
            else:
                publish(lambda: not result.done() and result.set_result(lines))

        Thread(
            target=read_file,
            name="valhallog-file-reader",
            daemon=True,
        ).start()
        return await result

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Apply a file worker result on the UI thread if it is still current."""
        if event.worker is not self._file_worker:
            return

        path = self._selected_path
        if path is None:
            return
        if event.state == WorkerState.ERROR:
            error = event.worker.error
            if isinstance(error, PermissionError):
                message = f"Permission denied: {path}"
            elif isinstance(error, FileNotFoundError):
                message = f"File not found: {path}"
            elif isinstance(error, OSError):
                message = f"Could not read {path}: {error.strerror or error}"
            else:
                message = f"Could not read {path}: {error or 'unknown error'}"
            self.query_one("#status", Static).update(message)
            self._file_worker = None
            return
        if event.state != WorkerState.SUCCESS:
            return

        self._raw_lines = list(event.worker.result or [])
        self._render_file_lines()
        self._file_worker = None

    def _render_file_lines(self) -> None:
        """Render the cached file lines using the active severity filter."""
        if self._selected_path is None or self._raw_lines is None:
            return
        visible_lines = filter_lines(self._raw_lines, self._active_level)
        log_viewer = self.query_one("#log-viewer", RichLog)
        log_viewer.clear()
        for line in visible_lines:
            log_viewer.write(line)
        self.query_one("#status", Static).update(
            f"Loaded {len(visible_lines)} of {len(self._raw_lines)} line(s) from "
            f"{self._selected_path} | Filter: {self._active_level.upper()}"
        )

    def on_select_changed(self, event: Select.Changed) -> None:
        """Apply a new level filter to the active source."""
        if event.select.id != "level-select" or not isinstance(event.value, str):
            return
        self._active_level = normalize_level(event.value)
        if self._selected_path is not None and self._raw_lines is not None:
            self._render_file_lines()
        elif self._selected_source is not None and self.config is not None:
            source = self._selected_source
            if self._following:
                self._stop_follow()
                self._start_journal_follow(source)
            else:
                self._stop_journal()
                self._start_journal_load(source, self.config.viewer.initial_lines)

    def _start_journal_load(self, source: SourceConfig, max_lines: int) -> None:
        """Clear the viewer and start reading a virtual journal source."""
        self.query_one("#log-title", Static).update(source.name)
        self.query_one("#log-viewer", RichLog).clear()
        self._raw_lines = None
        self.query_one("#status", Static).update(
            f"Loading {source.name} | Filter: {self._active_level.upper()}..."
        )
        self._journal_worker = self.run_worker(
            self._load_journal(source, max_lines, self._active_level),
            name="load-journal",
            group="journal-reader",
            exclusive=True,
            exit_on_error=False,
        )

    async def _load_journal(
        self, source: SourceConfig, max_lines: int, level: str
    ) -> None:
        """Stream journal output into the viewer while the source is selected."""
        log_viewer = self.query_one("#log-viewer", RichLog)
        status = self.query_one("#status", Static)
        line_count = 0
        try:
            async for line in JournalReader(source).iter_lines(max_lines, level):
                if self._selected_source is not source:
                    return
                log_viewer.write(line)
                line_count += 1
        except JournalError as exc:
            if self._selected_source is source:
                status.update(str(exc))
            return
        except OSError as exc:
            if self._selected_source is source:
                status.update(f"Could not start journalctl: {exc.strerror or exc}")
            return

        if self._selected_source is source:
            status.update(
                f"Loaded {line_count} journal line(s) from {source.name} | "
                f"Filter: {level.upper()}"
            )

    def action_toggle_follow(self) -> None:
        """Start or stop following the currently selected source."""
        status = self.query_one("#status", Static)
        if self._selected_source is not None:
            source = self._selected_source
            if self._following:
                self._stop_follow()
                status.update(
                    f"Follow: OFF | Filter: {self._active_level.upper()} | {source.name}"
                )
            else:
                self._start_journal_follow(source)
                status.update(
                    f"Follow: ON | Filter: {self._active_level.upper()} | {source.name}"
                )
            return
        if self._selected_path is None or self.config is None:
            status.update("Select a file before enabling follow mode")
            return

        if self._following:
            self._stop_follow()
            status.update(
                f"Follow: OFF | Filter: {self._active_level.upper()} | "
                f"{self._selected_path}"
            )
            return

        path = self._selected_path
        poll_ms = self.config.viewer.follow_poll_ms
        try:
            start_offset = path.stat().st_size
        except OSError:
            start_offset = 0
        self._following = True
        self._follow_worker = self.run_worker(
            self._follow_file(path, poll_ms, start_offset),
            name="follow-file",
            group="file-follow",
            exclusive=True,
            exit_on_error=False,
        )
        status.update(
            f"Follow: ON | Filter: {self._active_level.upper()} | {self._selected_path}"
        )

    def _stop_follow(self) -> None:
        """Request cancellation of the active file or journal follow worker."""
        self._following = False
        if self._follow_worker is not None and not self._follow_worker.is_finished:
            self._follow_worker.cancel()
        self._follow_worker = None
        if (
            self._journal_follow_worker is not None
            and not self._journal_follow_worker.is_finished
        ):
            self._journal_follow_worker.cancel()
        self._journal_follow_worker = None

    def _stop_journal(self) -> None:
        """Request cancellation of the active journal reader."""
        if self._journal_worker is not None and not self._journal_worker.is_finished:
            self._journal_worker.cancel()
        self._journal_worker = None

    def _stop_file(self) -> None:
        """Request cancellation of the active file reader."""
        if self._file_worker is not None and not self._file_worker.is_finished:
            self._file_worker.cancel()
        self._file_worker = None

    def _stop_readers(self) -> None:
        """Stop any reader whose output should no longer reach the viewer."""
        self._stop_follow()
        self._stop_file()
        self._stop_journal()

    def _start_journal_follow(self, source: SourceConfig) -> None:
        """Start a journalctl follow stream for the selected source."""
        if self.config is None:
            return
        self._stop_journal()
        self.query_one("#log-title", Static).update(source.name)
        self.query_one("#log-viewer", RichLog).clear()
        self._following = True
        self._journal_follow_worker = self.run_worker(
            self._follow_journal(
                source,
                self.config.viewer.initial_lines,
                self._active_level,
            ),
            name="follow-journal",
            group="journal-follow",
            exclusive=True,
            exit_on_error=False,
        )

    async def _follow_journal(
        self, source: SourceConfig, max_lines: int, level: str
    ) -> None:
        """Stream journalctl follow output until the worker is cancelled."""
        worker = get_current_worker()
        log_viewer = self.query_one("#log-viewer", RichLog)
        status = self.query_one("#status", Static)
        try:
            async for line in JournalReader(source).iter_lines(
                max_lines, level, follow=True
            ):
                if (
                    worker.is_cancelled
                    or not self._following
                    or self._selected_source is not source
                ):
                    return
                log_viewer.write(line)
        except JournalError as exc:
            if self._selected_source is source and self._following:
                self._following = False
                status.update(str(exc))
        except OSError as exc:
            if self._selected_source is source and self._following:
                self._following = False
                status.update(f"Could not start journalctl: {exc.strerror or exc}")

    async def _follow_file(self, path: Path, poll_ms: int, start_offset: int) -> None:
        """Poll for complete appended lines in a cancellable worker."""
        worker = get_current_worker()
        file = None
        offset = start_offset
        first_open = True
        delay = poll_ms / 1000

        try:
            while not worker.is_cancelled:
                try:
                    file_size = path.stat().st_size
                    if file is None or file_size < offset:
                        if file is not None:
                            file.close()
                        file = path.open("r", encoding="utf-8", errors="replace")
                        if first_open:
                            file.seek(min(start_offset, file_size))
                            offset = file.tell()
                            first_open = False
                        else:
                            offset = 0

                    file.seek(offset)
                    while True:
                        line = file.readline()
                        if not line:
                            break
                        if worker.is_cancelled:
                            break
                        if not line.endswith("\n"):
                            break
                        offset = file.tell()
                        self._append_follow_line(path, line.rstrip("\r\n"))
                except PermissionError:
                    self._set_follow_error(path, f"Permission denied: {path}")
                except FileNotFoundError:
                    self._set_follow_error(path, f"File not found: {path}")
                except OSError as exc:
                    self._set_follow_error(
                        path, f"Could not follow {path}: {exc.strerror or exc}"
                    )

                await asyncio.sleep(delay)
        finally:
            if file is not None:
                file.close()

    def _append_follow_line(self, path: Path, line: str) -> None:
        """Append a worker result only if it is still for the active file."""
        if self._following and self._selected_path == path:
            if self._raw_lines is None:
                self._raw_lines = []
            self._raw_lines.append(line)
            if should_show(line, self._active_level):
                self.query_one("#log-viewer", RichLog).write(line)

    def _set_follow_error(self, path: Path, message: str) -> None:
        """Show a follow error only if the file is still selected."""
        if self._following and self._selected_path == path:
            self.query_one("#status", Static).update(message)

    def on_unmount(self) -> None:
        """Stop the polling worker when the app exits."""
        self._stop_readers()

    def action_show_help(self) -> None:
        """Open the keyboard reference modal."""
        self.push_screen(
            HelpScreen(self.config.config_path if self.config is not None else None)
        )


def main() -> None:
    """Run Valhallog."""
    ValhallogApp().run()
