"""The runnable Valhallog application."""

import asyncio
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from pathlib import Path
from threading import Event, Thread

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    RichLog,
    Select,
    Static,
    Tree,
)
from textual.worker import Worker, WorkerState, get_current_worker

from .config import ConfigError, load_config, resolve_user_home
from .config_editor import (
    SourceAlreadyExistsError,
    add_directory_source,
    rename_source,
)
from .filters import filter_lines, normalize_level, should_show
from .highlighting import highlight_log_line
from .models import AppConfig, SourceConfig
from .sources.files import FileLogReader, scan_directory
from .sources.journal import JournalError, JournalReader
from .time_filters import TimeWindow
from .widgets.source_picker import (
    AddSourceScreen,
    AddSourceSelection,
    RenameSourceScreen,
)
from .widgets.verbosity import VimVerbositySelect


SOURCE_PANEL_DEFAULT_PERCENT = 20
SOURCE_PANEL_MIN_PERCENT = 15
SOURCE_PANEL_MAX_PERCENT = 60
SOURCE_PANEL_STEP_PERCENT = 5
LOG_HORIZONTAL_SCROLL_STEP = 2
FILE_LOAD_BATCH_SIZE = 250
_VALKNUT_BASE = r"""
 ___      ___ ________  ___  ___  ________  ___       ___       ________  ________ 
|\  \    /  /|\   __  \|\  \|\  \|\   __  \|\  \     |\  \     |\   __  \|\   ____\    
\ \  \  /  / | \  \|\  \ \  \\\  \ \  \|\  \ \  \    \ \  \    \ \  \|\  \ \  \___|    
 \ \  \/  / / \ \   __  \ \   __  \ \   __  \ \  \    \ \  \    \ \  \\\  \ \  \  ___  
  \ \    / /   \ \  \ \  \ \  \ \  \ \  \ \  \ \  \____\ \  \____\ \  \\\  \ \  \|\  \ 
   \ \__/ /     \ \__\ \__\ \__\ \__\ \__\ \__\ \_______\ \_______\ \_______\ \_______\
    \|__|/       \|__|\|__|\|__|\|__|\|__|\|__|\|_______|\|_______|\|_______|\|_______|
"""


def _valknut_splash(_width: int, _height: int) -> str:
    """Build the exact ASCII artwork while preserving each line's spacing."""
    base_lines = _VALKNUT_BASE.strip("\n").splitlines()
    base_width = max(map(len, base_lines))
    padded_lines = [line.ljust(base_width) for line in base_lines]
    return "\n".join((*padded_lines, ""))


class ValknutSplash(Static):
    """Display a responsive ASCII Valknut in the empty log pane."""

    def on_mount(self) -> None:
        self._refresh_art()

    def on_resize(self, _event: events.Resize) -> None:
        self._refresh_art()

    def _refresh_art(self) -> None:
        if self.size.width and self.size.height:
            self.update(_valknut_splash(self.size.width, self.size.height))


class FollowIndicator(Static):
    """Animate a one-line visual cue while a source is being followed."""

    _FRAMES = ("|", "/", "-", "\\")

    def on_mount(self) -> None:
        self._frame_index = 0
        self.styles.display = "none"
        self.set_interval(0.35, self._advance)

    def _advance(self) -> None:
        """Advance the spinner without changing the log contents."""
        if self.styles.display == "none":
            return
        self._frame_index = (self._frame_index + 1) % len(self._FRAMES)
        self.update(f"{self._FRAMES[self._frame_index]} Following — waiting for new lines")

    def start(self) -> None:
        """Show and reset the follow-mode animation."""
        self._frame_index = 0
        self.update(f"{self._FRAMES[0]} Following — waiting for new lines")
        self.styles.display = "block"

    def stop(self) -> None:
        """Hide the follow-mode animation."""
        self.styles.display = "none"


class LoadIndicator(Static):
    """Animate file-loading progress without blocking the log viewer."""

    _FRAMES = ("|", "/", "-", "\\")

    def on_mount(self) -> None:
        self._frame_index = 0
        self._file_name = ""
        self._bytes_read = 0
        self._total_bytes = 0
        self.styles.display = "none"
        self.set_interval(0.35, self._advance)

    def _render_indicator(self) -> None:
        if self._total_bytes:
            percent = min(100, int(self._bytes_read * 100 / self._total_bytes))
            progress = f"{percent:3d}%"
        else:
            progress = "  0%"
        self.update(
            f"{self._FRAMES[self._frame_index]} Loading {self._file_name}… "
            f"{progress}"
        )

    def _advance(self) -> None:
        """Advance the spinner while preserving the latest progress."""
        if self.styles.display == "none":
            return
        self._frame_index = (self._frame_index + 1) % len(self._FRAMES)
        self._render_indicator()

    def start(self, file_name: str, total_bytes: int) -> None:
        """Show a fresh loading indicator for one file."""
        self._frame_index = 0
        self._file_name = file_name
        self._bytes_read = 0
        self._total_bytes = total_bytes
        self._render_indicator()
        self.styles.display = "block"

    def update_progress(self, bytes_read: int) -> None:
        """Update the displayed byte progress."""
        self._bytes_read = bytes_read
        self._render_indicator()

    def stop(self) -> None:
        """Hide the loading indicator."""
        self.styles.display = "none"


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
                "a  Add a folder source\n"
                "r  Rename the highlighted source\n"
                "v  Focus verbosity menu\n"
                "Time  Open the time-window menu\n"
                "j/k  Move through sources or scroll logs\n"
                "Shift+J/K  Page through logs\n"
                "Shift+H  Focus sources\n"
                "Shift+L  Focus log viewer\n"
                "h  Scroll left or collapse\n"
                "l  Scroll right or expand/open\n"
                "+/-  Widen or narrow the sources panel\n"
                "Tab  Move focus\n"
                "?  Open this help\n"
                "Escape  Close this help\n\n"
                "Choose a source from the tree. Use the level selector to filter\n"
                "plain files or set the native journal priority. Use the time menu\n"
                "to filter both source types by an inclusive timestamp window.\n"
                "The viewer highlights timestamps, severities, URLs, IP addresses,\n"
                "MAC addresses, process IDs, paths, services, devices, ports,\n"
                "and common structured log fields.\n\n"
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


@dataclass(frozen=True)
class TimeFilterSelection:
    """The result returned by the time-filter menu."""

    window: TimeWindow | None


class TimeFilterScreen(ModalScreen[TimeFilterSelection | None]):
    """Edit the inclusive time window used by the log viewer."""

    BINDINGS = [
        Binding("J", "decrease_window", "Decrease minutes", show=False),
        Binding("K", "increase_window", "Increase minutes", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, active_window: TimeWindow | None):
        super().__init__()
        if active_window is None:
            now = datetime.now().astimezone().replace(second=0, microsecond=0)
            self._center = now
            self._minutes = 5
        else:
            self._center = active_window.center
            self._minutes = active_window.minutes

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Time filter", id="time-filter-title"),
            Static(
                "Select a center date and time. J/K and the buttons adjust the ± window.",
                id="time-filter-instructions",
            ),
            Horizontal(
                Static("Date"),
                TimeFilterInput(self._center.strftime("%Y-%m-%d"), id="time-date"),
                id="time-date-row",
            ),
            Horizontal(
                Static("Time"),
                TimeFilterInput(self._center.strftime("%H:%M:%S"), id="time-of-day"),
                id="time-of-day-row",
            ),
            Horizontal(
                Static("Window (minutes)"),
                Button("−", id="time-minus", compact=True),
                TimeFilterInput(str(self._minutes), id="time-window"),
                Button("+", id="time-plus", compact=True),
                id="time-window-controls",
            ),
            Static("", id="time-filter-error"),
            Horizontal(
                Button("Apply", id="time-apply", variant="primary"),
                Button("Clear", id="time-clear"),
                Button("Cancel", id="time-cancel"),
                id="time-filter-actions",
            ),
            id="time-filter-dialog",
        )

    def _adjust_window(self, amount: int) -> None:
        window_input = self.query_one("#time-window", Input)
        try:
            minutes = int(window_input.value)
        except ValueError:
            minutes = self._minutes
        self._minutes = max(0, min(1440, minutes + amount))
        window_input.value = str(self._minutes)
        self.query_one("#time-filter-error", Static).update("")

    def action_decrease_window(self) -> None:
        """Decrease the window while this menu is open."""
        self._adjust_window(-1)

    def action_increase_window(self) -> None:
        """Increase the window while this menu is open."""
        self._adjust_window(1)

    def _parse_window(self) -> TimeWindow | None:
        date_text = self.query_one("#time-date", Input).value.strip()
        time_text = self.query_one("#time-of-day", Input).value.strip()
        minutes_text = self.query_one("#time-window", Input).value.strip()
        try:
            selected_date = date.fromisoformat(date_text)
            try:
                selected_time = time.fromisoformat(time_text)
            except ValueError:
                selected_time = datetime.strptime(time_text, "%H:%M").time()
            minutes = int(minutes_text)
        except ValueError:
            self.query_one("#time-filter-error", Static).update(
                "Use a valid date, time, and non-negative minute value."
            )
            return None
        if minutes < 0 or minutes > 1440:
            self.query_one("#time-filter-error", Static).update(
                "Window must be between 0 and 1440 minutes."
            )
            return None
        return TimeWindow.from_values(selected_date, selected_time, minutes)

    def action_apply(self) -> None:
        """Validate and apply the entered time window."""
        window = self._parse_window()
        if window is not None:
            self.dismiss(TimeFilterSelection(window))

    def action_clear(self) -> None:
        """Clear the active time filter."""
        self.dismiss(TimeFilterSelection(None))

    def action_cancel(self) -> None:
        """Close the menu without changing the active filter."""
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle the physical time-filter controls."""
        actions = {
            "time-minus": self.action_decrease_window,
            "time-plus": self.action_increase_window,
            "time-apply": self.action_apply,
            "time-clear": self.action_clear,
            "time-cancel": self.action_cancel,
        }
        action = actions.get(event.button.id)
        if action is not None:
            action()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Allow Enter to apply the menu from any input."""
        self.action_apply()

    def on_key(self, event: events.Key) -> None:
        """Keep shifted J/K active even when an input has focus."""
        if event.key in {"J", "j"}:
            self.action_decrease_window()
            event.stop()
            event.prevent_default()
        elif event.key in {"K", "k"}:
            self.action_increase_window()
            event.stop()
            event.prevent_default()


class TimeFilterInput(Input):
    """An input that keeps the modal's J/K controls active while focused."""

    def on_key(self, event: events.Key) -> None:
        if event.key in {"J", "j"}:
            screen = self.screen
            if isinstance(screen, TimeFilterScreen):
                screen.action_decrease_window()
                event.stop()
                event.prevent_default()
        elif event.key in {"K", "k"}:
            screen = self.screen
            if isinstance(screen, TimeFilterScreen):
                screen.action_increase_window()
                event.stop()
                event.prevent_default()


class ValhallogApp(App[None]):
    """A minimal Textual app shell for Valhallog."""

    TITLE = "Valhallog"
    CSS_PATH = "app.tcss"
    config: AppConfig | None = None
    _selected_path: Path | None = None
    _selected_source: SourceConfig | None = None
    _active_level = "all"
    _active_time_window: TimeWindow | None = None
    _raw_lines: list[str] | None = None
    _following = False
    _follow_worker: Worker[None] | None = None
    _journal_follow_worker: Worker[None] | None = None
    _file_worker: Worker[None] | None = None
    _file_loading = False
    _file_bytes_read = 0
    _file_total_bytes = 0
    _file_visible_count = 0
    _journal_worker: Worker[None] | None = None

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("?", "show_help", "Help"),
        Binding("a", "add_source", "Add source"),
        Binding("r", "rename_source", "Rename source"),
        Binding("v", "focus_level_select", "Verbosity"),
        Binding("j", "source_down", "Down"),
        Binding("k", "source_up", "Up"),
        Binding("J", "log_page_down", "Page down", key_display="Shift+J"),
        Binding("K", "log_page_up", "Page up", key_display="Shift+K"),
        # Printable shifted letters arrive from the terminal as uppercase keys.
        Binding("H", "focus_sources", "Sources", key_display="Shift+H"),
        Binding("L", "focus_log_viewer", "Log viewer", key_display="Shift+L"),
        Binding("h", "vim_left", "Left"),
        Binding("l", "vim_right", "Right"),
        Binding("plus,equals_sign", "increase_source_panel", "Wider", key_display="+ / ="),
        Binding("minus", "decrease_source_panel", "Narrower"),
        Binding("tab", "focus_next", "Focus next"),
        Binding("f", "toggle_follow", "Follow"),
    ]

    _HIDDEN_WHILE_VERBOSITY_MENU_OPEN = frozenset(
        {
            "show_help",
            "add_source",
            "rename_source",
            "focus_level_select",
            "source_down",
            "source_up",
            "log_page_down",
            "log_page_up",
            "focus_sources",
            "focus_log_viewer",
            "vim_left",
            "vim_right",
            "increase_source_panel",
            "decrease_source_panel",
            "toggle_follow",
            "command_palette",
        }
    )
    _HIDDEN_WHILE_LOG_VIEWER_FOCUSED = frozenset(
        {
            "add_source",
            "rename_source",
        }
    )
    _HIDDEN_WHILE_SOURCE_TREE_FOCUSED = frozenset(
        {
            "log_page_down",
            "log_page_up",
        }
    )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Hide shortcuts that don't apply to the current focus context."""
        try:
            menu_open = self.query_one("#level-select", Select).expanded
        except NoMatches:
            menu_open = False
        if menu_open and action in self._HIDDEN_WHILE_VERBOSITY_MENU_OPEN:
            return False
        focused = self.focused
        if isinstance(focused, RichLog) and action in self._HIDDEN_WHILE_LOG_VIEWER_FOCUSED:
            return False
        if isinstance(focused, Tree) and action in self._HIDDEN_WHILE_SOURCE_TREE_FOCUSED:
            return False
        return super().check_action(action, parameters)

    def compose(self) -> ComposeResult:
        """Describe the widgets that make up the first screen."""
        yield Header()
        yield Vertical(
            Horizontal(
                VimVerbositySelect(
                    [
                        ("All", "all"),
                        ("Debug", "debug"),
                        ("Info", "info"),
                        ("Warning", "warning"),
                        ("Error", "error"),
                        ("Critical", "critical"),
                    ],
                    value="all",
                    allow_blank=False,
                    id="level-select",
                ),
                Button("Time: off", id="time-filter"),
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
                    ValknutSplash(id="splash"),
                    RichLog(
                        id="log-viewer",
                        highlight=False,
                        markup=False,
                        max_lines=None,
                    ),
                    LoadIndicator(id="load-indicator"),
                    FollowIndicator(id="follow-indicator"),
                    id="log-pane",
                ),
                id="main-content",
            ),
            id="body",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load configured source names while keeping the UI responsive."""
        self._source_width_percent = SOURCE_PANEL_DEFAULT_PERCENT
        self._selected_path = None
        self._selected_source = None
        self._active_level = "all"
        self._active_time_window = None
        self._raw_lines = None
        self._following = False
        self._follow_worker = None
        self._journal_follow_worker = None
        self._file_worker = None
        self._file_loading = False
        self._file_bytes_read = 0
        self._file_total_bytes = 0
        self._file_visible_count = 0
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
            self._refresh_source_tree()

        self.query_one("#splash", ValknutSplash).styles.display = "block"
        self._update_time_filter_button()

    def _refresh_source_tree(self) -> None:
        """Rebuild the source tree after loading or adding a source."""
        if self.config is None:
            return
        source_tree = self.query_one("#source-tree", Tree)
        status = self.query_one("#status", Static)
        source_tree.root.remove_children()
        file_count = 0
        missing_count = 0
        empty_count = 0
        for source in self.config.sources:
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
        if self.config.sources:
            status.update(
                f"Loaded {len(self.config.sources)} source(s), {file_count} file(s)"
                f"{missing_text}{empty_text}"
            )
        else:
            status.update("No configured sources")

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
            self._start_file_load(event.node.data)
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

    def _start_file_load(self, path: Path) -> None:
        """Start a background read for the selected file."""
        self.query_one("#splash", Static).styles.display = "none"
        log_viewer = self.query_one("#log-viewer", RichLog)
        log_title = self.query_one("#log-title", Static)
        status = self.query_one("#status", Static)
        log_title.update(path.name)
        log_viewer.clear()
        status.update(f"Loading {path}... | {self._filter_summary()}")
        self._raw_lines = []
        self._file_loading = True
        self._file_bytes_read = 0
        self._file_visible_count = 0
        try:
            self._file_total_bytes = path.stat().st_size
        except OSError:
            self._file_total_bytes = 0
        self._show_load_indicator(path.name, self._file_total_bytes)
        self._file_worker = self.run_worker(
            self._read_file_worker(path),
            name="load-file",
            group="file-reader",
            exclusive=True,
            exit_on_error=False,
        )

    async def _read_file_worker(self, path: Path) -> None:
        """Read and publish file batches without blocking the UI loop."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[list[str], int] | BaseException | None]
        queue = asyncio.Queue()
        stop_event = Event()

        def publish(callback) -> None:
            """Publish a reader result unless the app loop is already closed."""
            try:
                loop.call_soon_threadsafe(callback)
            except RuntimeError:
                pass

        def read_file() -> None:
            try:
                for batch, bytes_read in FileLogReader(path).iter_line_batches(
                    FILE_LOAD_BATCH_SIZE
                ):
                    if stop_event.is_set():
                        return
                    publish(
                        lambda batch=batch, bytes_read=bytes_read: queue.put_nowait(
                            (batch, bytes_read)
                        )
                    )
            except Exception as error:
                publish(lambda error=error: queue.put_nowait(error))
            finally:
                publish(lambda: queue.put_nowait(None))

        Thread(
            target=read_file,
            name="valhallog-file-reader",
            daemon=True,
        ).start()
        try:
            while True:
                item = await queue.get()
                if item is None:
                    return
                if isinstance(item, BaseException):
                    raise item
                batch, bytes_read = item
                if self._selected_path != path:
                    return
                self._append_file_batch(path, batch, bytes_read)
                await asyncio.sleep(0)
        finally:
            stop_event.set()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Apply a file worker result on the UI thread if it is still current."""
        if event.worker is not self._file_worker:
            return

        path = self._selected_path
        if path is None:
            return
        if event.state == WorkerState.ERROR:
            self._file_loading = False
            self._hide_load_indicator()
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

        self._file_loading = False
        self._hide_load_indicator()
        self._update_file_status()
        self._file_worker = None

    def _append_file_batch(
        self, path: Path, lines: list[str], bytes_read: int
    ) -> None:
        """Append one background batch to the active file view."""
        if self._selected_path != path:
            return
        if self._raw_lines is None:
            self._raw_lines = []
        self._raw_lines.extend(lines)
        visible_lines = [
            line
            for line in lines
            if should_show(line, self._active_level, self._active_time_window)
        ]
        self._write_log_lines(visible_lines)
        visible_count = len(visible_lines)
        self._file_visible_count += visible_count
        self._file_bytes_read = bytes_read
        self._update_load_indicator(bytes_read)
        self._update_file_status()

    def _update_file_status(self) -> None:
        """Update the file count/progress status without rereading the file."""
        if self._selected_path is None or self._raw_lines is None:
            return
        if self._file_loading:
            self.query_one("#status", Static).update(
                f"Loading {self._selected_path.name}: {self._file_visible_count} visible of "
                f"{len(self._raw_lines)} line(s) | {self._filter_summary()}"
            )
            return
        self.query_one("#status", Static).update(
            f"Loaded {self._file_visible_count} of {len(self._raw_lines)} line(s) from "
            f"{self._selected_path} | {self._filter_summary()}"
        )

    def _render_file_lines(self) -> None:
        """Render the cached file lines using the active severity filter."""
        if self._selected_path is None or self._raw_lines is None:
            return
        visible_lines = filter_lines(
            self._raw_lines,
            self._active_level,
            self._active_time_window,
        )
        log_viewer = self.query_one("#log-viewer", RichLog)
        log_viewer.clear()
        self._write_log_lines(visible_lines)
        self._file_visible_count = len(visible_lines)
        self._update_file_status()

    def _write_log_lines(self, lines: list[str]) -> None:
        """Write a batch without recalculating the scroll position per line."""
        log_viewer = self.query_one("#log-viewer", RichLog)
        auto_scroll = log_viewer.auto_scroll
        log_viewer.auto_scroll = False
        try:
            for line in lines:
                log_viewer.write(highlight_log_line(line))
        finally:
            log_viewer.auto_scroll = auto_scroll
        if auto_scroll:
            log_viewer.scroll_end(animate=False, immediate=False, x_axis=False)

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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Open the time-filter menu from the top-bar button."""
        if event.button.id == "time-filter":
            self.push_screen(
                TimeFilterScreen(self._active_time_window),
                self._apply_time_filter_selection,
            )

    def _apply_time_filter_selection(
        self, selection: TimeFilterSelection | None
    ) -> None:
        """Apply or clear a time filter after the modal closes."""
        if selection is None:
            return
        self._active_time_window = selection.window
        self._update_time_filter_button()
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
        else:
            self.query_one("#status", Static).update(
                f"No source selected | {self._filter_summary()}"
            )

    def _filter_summary(self) -> str:
        """Return the active filter state for status messages."""
        summary = f"Filter: {self._active_level.upper()}"
        if self._active_time_window is not None:
            summary += f" | Time: {self._active_time_window.label()}"
        return summary

    def _update_time_filter_button(self) -> None:
        """Keep the top-bar button label synchronized with the active filter."""
        try:
            button = self.query_one("#time-filter", Button)
        except NoMatches:
            return
        if self._active_time_window is None:
            button.label = "Time: off"
        else:
            button.label = f"Time: ±{self._active_time_window.minutes}m"

    def _start_journal_load(self, source: SourceConfig, max_lines: int) -> None:
        """Clear the viewer and start reading a virtual journal source."""
        self.query_one("#splash", Static).styles.display = "none"
        self.query_one("#log-title", Static).update(source.name)
        self.query_one("#log-viewer", RichLog).clear()
        self._raw_lines = None
        self.query_one("#status", Static).update(
            f"Loading {source.name} | {self._filter_summary()}..."
        )
        self._journal_worker = self.run_worker(
            self._load_journal(
                source,
                max_lines,
                self._active_level,
                self._active_time_window,
            ),
            name="load-journal",
            group="journal-reader",
            exclusive=True,
            exit_on_error=False,
        )

    async def _load_journal(
        self,
        source: SourceConfig,
        max_lines: int,
        level: str,
        time_window: TimeWindow | None,
    ) -> None:
        """Stream journal output into the viewer while the source is selected."""
        log_viewer = self.query_one("#log-viewer", RichLog)
        status = self.query_one("#status", Static)
        line_count = 0
        try:
            reader = JournalReader(source)
            if time_window is None:
                lines = reader.iter_lines(max_lines, level)
            else:
                lines = reader.iter_lines(None, level, time_window=time_window)
            async for line in lines:
                if self._selected_source is not source:
                    return
                log_viewer.write(highlight_log_line(line))
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
                f"{self._filter_summary()}"
            )

    def action_toggle_follow(self) -> None:
        """Start or stop following the currently selected source."""
        status = self.query_one("#status", Static)
        if self._selected_source is not None:
            source = self._selected_source
            if self._following:
                self._stop_follow()
                status.update(
                    f"Follow: OFF | {self._filter_summary()} | {source.name}"
                )
            else:
                self._start_journal_follow(source)
                status.update(
                    f"Follow: ON | {self._filter_summary()} | {source.name}"
                )
            return
        if self._selected_path is None or self.config is None:
            status.update("Select a file before enabling follow mode")
            return

        if self._following:
            self._stop_follow()
            status.update(
                f"Follow: OFF | {self._filter_summary()} | "
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
        self._show_follow_indicator()
        self._follow_worker = self.run_worker(
            self._follow_file(path, poll_ms, start_offset),
            name="follow-file",
            group="file-follow",
            exclusive=True,
            exit_on_error=False,
        )
        status.update(
            f"Follow: ON | {self._filter_summary()} | {self._selected_path}"
        )

    def _stop_follow(self) -> None:
        """Request cancellation of the active file or journal follow worker."""
        self._following = False
        self._hide_follow_indicator()
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
        self._file_loading = False
        self._file_visible_count = 0
        self._hide_load_indicator()
        if self._file_worker is not None and not self._file_worker.is_finished:
            self._file_worker.cancel()
        self._file_worker = None

    def _stop_readers(self) -> None:
        """Stop any reader whose output should no longer reach the viewer."""
        self._stop_follow()
        self._stop_file()
        self._stop_journal()

    def _show_follow_indicator(self) -> None:
        """Show the animated footer beneath the log viewer."""
        try:
            self.query_one("#follow-indicator", FollowIndicator).start()
        except NoMatches:
            pass

    def _show_load_indicator(self, file_name: str, total_bytes: int) -> None:
        """Show the animated progress footer for a file load."""
        try:
            self.query_one("#load-indicator", LoadIndicator).start(
                file_name, total_bytes
            )
        except NoMatches:
            pass

    def _update_load_indicator(self, bytes_read: int) -> None:
        """Update the animated progress footer for a file load."""
        try:
            self.query_one("#load-indicator", LoadIndicator).update_progress(
                bytes_read
            )
        except NoMatches:
            pass

    def _hide_load_indicator(self) -> None:
        """Hide the animated progress footer for a file load."""
        try:
            self.query_one("#load-indicator", LoadIndicator).stop()
        except NoMatches:
            pass

    def _hide_follow_indicator(self) -> None:
        """Hide the animated footer beneath the log viewer."""
        try:
            self.query_one("#follow-indicator", FollowIndicator).stop()
        except NoMatches:
            pass

    def _start_journal_follow(self, source: SourceConfig) -> None:
        """Start a journalctl follow stream for the selected source."""
        if self.config is None:
            return
        self.query_one("#splash", Static).styles.display = "none"
        self._stop_journal()
        self.query_one("#log-title", Static).update(source.name)
        self.query_one("#log-viewer", RichLog).clear()
        self._following = True
        self._show_follow_indicator()
        self._journal_follow_worker = self.run_worker(
            self._follow_journal(
                source,
                self.config.viewer.initial_lines,
                self._active_level,
                self._active_time_window,
            ),
            name="follow-journal",
            group="journal-follow",
            exclusive=True,
            exit_on_error=False,
        )

    async def _follow_journal(
        self,
        source: SourceConfig,
        max_lines: int,
        level: str,
        time_window: TimeWindow | None,
    ) -> None:
        """Stream journalctl follow output until the worker is cancelled."""
        worker = get_current_worker()
        log_viewer = self.query_one("#log-viewer", RichLog)
        status = self.query_one("#status", Static)
        try:
            reader = JournalReader(source)
            if time_window is None:
                lines = reader.iter_lines(max_lines, level, follow=True)
            else:
                lines = reader.iter_lines(
                    None, level, follow=True, time_window=time_window
                )
            async for line in lines:
                if (
                    worker.is_cancelled
                    or not self._following
                    or self._selected_source is not source
                ):
                    return
                log_viewer.write(highlight_log_line(line))
        except JournalError as exc:
            if self._selected_source is source and self._following:
                self._following = False
                self._hide_follow_indicator()
                status.update(str(exc))
        except OSError as exc:
            if self._selected_source is source and self._following:
                self._following = False
                self._hide_follow_indicator()
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
            if should_show(line, self._active_level, self._active_time_window):
                self.query_one("#log-viewer", RichLog).write(
                    highlight_log_line(line)
                )

    def _set_follow_error(self, path: Path, message: str) -> None:
        """Show a follow error only if the file is still selected."""
        if self._following and self._selected_path == path:
            self.query_one("#status", Static).update(message)

    def on_unmount(self) -> None:
        """Stop the polling worker when the app exits."""
        self._stop_readers()

    def action_add_source(self) -> None:
        """Open the home-directory picker for one new folder source."""
        if self.config is None:
            self.query_one("#status", Static).update(
                "Cannot add a source until the configuration is loaded"
            )
            return
        self.push_screen(AddSourceScreen(resolve_user_home()), self._add_source)

    def action_focus_level_select(self) -> None:
        """Focus the log-level selector."""
        level_select = self.query_one("#level-select", Select)
        level_select.focus()
        level_select.action_show_overlay()

    def action_focus_sources(self) -> None:
        """Focus the left sources panel."""
        self.query_one("#source-tree", Tree).focus()

    def action_focus_log_viewer(self) -> None:
        """Focus the right log viewer panel."""
        self.query_one("#log-viewer", RichLog).focus()

    def action_increase_source_panel(self) -> None:
        """Widen the sources panel by one split step."""
        self._set_source_panel_width(
            self._source_width_percent + SOURCE_PANEL_STEP_PERCENT
        )

    def action_decrease_source_panel(self) -> None:
        """Narrow the sources panel by one split step."""
        self._set_source_panel_width(
            self._source_width_percent - SOURCE_PANEL_STEP_PERCENT
        )

    def _set_source_panel_width(self, width_percent: int) -> None:
        """Apply a bounded percentage width to the left panel."""
        self._source_width_percent = max(
            SOURCE_PANEL_MIN_PERCENT,
            min(SOURCE_PANEL_MAX_PERCENT, width_percent),
        )
        source_pane = self.query_one("#source-pane", Vertical)
        source_pane.styles.width = f"{self._source_width_percent}%"

    def _source_cursor(self) -> tuple[Tree, object] | None:
        """Return the source tree and its highlighted node, if any."""
        source_tree = self.query_one("#source-tree", Tree)
        node = source_tree.cursor_node
        return (source_tree, node) if node is not None else None

    def action_source_down(self) -> None:
        """Scroll the log or move the source-tree cursor down."""
        log_viewer = self.query_one("#log-viewer", RichLog)
        if log_viewer.has_focus:
            log_viewer.action_scroll_down()
            return
        source_tree = self.query_one("#source-tree", Tree)
        source_tree.focus()
        source_tree.action_cursor_down()

    def action_source_up(self) -> None:
        """Scroll the log or move the source-tree cursor up."""
        log_viewer = self.query_one("#log-viewer", RichLog)
        if log_viewer.has_focus:
            log_viewer.action_scroll_up()
            return
        source_tree = self.query_one("#source-tree", Tree)
        source_tree.focus()
        source_tree.action_cursor_up()

    def action_log_page_down(self) -> None:
        """Scroll the log viewer down by one page when it has focus."""
        log_viewer = self.query_one("#log-viewer", RichLog)
        if log_viewer.has_focus:
            log_viewer.action_page_down()

    def action_log_page_up(self) -> None:
        """Scroll the log viewer up by one page when it has focus."""
        log_viewer = self.query_one("#log-viewer", RichLog)
        if log_viewer.has_focus:
            log_viewer.action_page_up()

    def action_source_collapse(self) -> None:
        """Collapse the highlighted source or its parent folder."""
        cursor = self._source_cursor()
        if cursor is None:
            return
        source_tree, node = cursor
        if node.allow_expand:
            node.collapse()
            return
        parent = node.parent
        if parent is not None and parent.allow_expand:
            parent.collapse()
            source_tree.move_cursor(parent)

    def action_source_expand_or_open(self) -> None:
        """Expand a source node, or open a highlighted log file/source."""
        cursor = self._source_cursor()
        if cursor is None:
            return
        source_tree, node = cursor
        if node.allow_expand:
            node.expand()
        else:
            source_tree.select_node(node)

    def action_vim_left(self) -> None:
        """Scroll the log left or collapse the highlighted source tree node."""
        log_viewer = self.query_one("#log-viewer", RichLog)
        if log_viewer.has_focus:
            for _ in range(LOG_HORIZONTAL_SCROLL_STEP):
                log_viewer.action_scroll_left()
            return
        source_tree = self.query_one("#source-tree", Tree)
        if source_tree.has_focus:
            self.action_source_collapse()

    def action_vim_right(self) -> None:
        """Scroll the log right or expand/open the highlighted source node."""
        log_viewer = self.query_one("#log-viewer", RichLog)
        if log_viewer.has_focus:
            for _ in range(LOG_HORIZONTAL_SCROLL_STEP):
                log_viewer.action_scroll_right()
            return
        source_tree = self.query_one("#source-tree", Tree)
        if source_tree.has_focus:
            self.action_source_expand_or_open()

    def _add_source(self, selection: AddSourceSelection | None) -> None:
        """Persist a confirmed picker selection and refresh the source tree."""
        if selection is None or self.config is None:
            return

        status = self.query_one("#status", Static)
        try:
            home = resolve_user_home().resolve(strict=False)
            selected_path = selection.path.resolve(strict=False)
            if not selected_path.is_relative_to(home):
                raise ValueError("The selected folder must be inside your home directory")
            source = add_directory_source(
                self.config.config_path,
                selected_path,
                recursive=selection.recursive,
                user_home=home,
                name=selection.name,
            )
        except SourceAlreadyExistsError as exc:
            status.update(str(exc))
            return
        except (OSError, ValueError) as exc:
            status.update(f"Could not add source: {exc}")
            return

        self.config = replace(self.config, sources=(*self.config.sources, source))
        self._refresh_source_tree()
        status.update(
            f"Added source '{source.name}' | Recursive: "
            f"{'ON' if source.recursive else 'OFF'}"
        )

    def action_rename_source(self) -> None:
        """Open the rename dialog for the highlighted source node."""
        if self.config is None:
            return
        source_tree = self.query_one("#source-tree", Tree)
        node = source_tree.cursor_node
        if node is None or not isinstance(node.data, SourceConfig):
            self.query_one("#status", Static).update(
                "Highlight a configured source before renaming it"
            )
            return
        source = node.data
        self.push_screen(
            RenameSourceScreen(source.name),
            lambda new_name, source=source: self._rename_source(source, new_name),
        )

    def _rename_source(self, source: SourceConfig, new_name: str | None) -> None:
        """Persist a confirmed rename and update the in-memory source."""
        if new_name is None or self.config is None:
            return
        status = self.query_one("#status", Static)
        try:
            renamed = rename_source(
                self.config.config_path,
                source,
                new_name=new_name,
                user_home=resolve_user_home(),
            )
        except (OSError, ValueError) as exc:
            status.update(f"Could not rename source: {exc}")
            return

        was_selected = self._selected_source is source
        if was_selected:
            self._stop_readers()
        sources = list(self.config.sources)
        try:
            source_index = sources.index(source)
        except ValueError:
            status.update(f"Could not rename source: {source.name} was not found")
            return
        sources[source_index] = renamed
        self.config = replace(self.config, sources=tuple(sources))
        if was_selected:
            self._selected_source = renamed
        self._refresh_source_tree()
        status.update(f"Renamed source to '{renamed.name}'")
        if was_selected:
            self._start_journal_load(renamed, self.config.viewer.initial_lines)

    def action_show_help(self) -> None:
        """Open the keyboard reference modal."""
        self.push_screen(
            HelpScreen(self.config.config_path if self.config is not None else None)
        )


def main() -> None:
    """Run Valhallog."""
    ValhallogApp().run()
