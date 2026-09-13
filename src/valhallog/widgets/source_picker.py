"""The modal used to choose a directory source."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DirectoryTree, Input, Static


class FoldersOnlyTree(DirectoryTree):
    """Show every directory, including hidden directories, but no files."""

    @staticmethod
    def filter_paths(paths: Iterable[Path]) -> list[Path]:
        return [path for path in paths if path.is_dir()]


@dataclass(frozen=True)
class AddSourceSelection:
    """The confirmed choices returned by :class:`AddSourceScreen`."""

    path: Path
    recursive: bool
    name: str


class AddSourceScreen(ModalScreen[AddSourceSelection | None]):
    """Choose one directory and its recursive-scan setting."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
    ]

    def __init__(self, home: Path):
        super().__init__()
        self.home = Path(home).expanduser().resolve(strict=False)
        self.selected_path: Path | None = None

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Add log source", id="add-source-title"),
            Static(
                "Choose a folder from your home directory:",
                id="add-source-instructions",
            ),
            FoldersOnlyTree(self.home, id="add-source-tree"),
            Static("No folder selected", id="add-source-selection"),
            Input(placeholder="Source name", id="add-source-name"),
            Checkbox("Scan recursively", value=False, id="add-source-recursive"),
            Horizontal(
                Button("Add", id="add-source", variant="primary", disabled=True),
                Button("Cancel", id="cancel-source"),
                id="add-source-actions",
            ),
            id="add-source-dialog",
        )

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        """Remember the selected directory and enable confirmation."""
        self._select_directory(event.path)

    def _select_directory(self, path: Path) -> None:
        """Update the selection; kept separate so it is easy to test."""
        self.selected_path = Path(path).resolve(strict=False)
        self.query_one("#add-source-selection", Static).update(
            f"Selected folder: {self.selected_path}"
        )
        name_input = self.query_one("#add-source-name", Input)
        name_input.value = self.selected_path.name
        name_input.styles.display = "block"
        name_input.focus()
        self._update_add_button()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Enable Add only when a folder and non-empty name are present."""
        if event.input.id == "add-source-name":
            self._update_add_button()

    def _update_add_button(self) -> None:
        """Keep the confirmation button in sync with the name input."""
        name = self.query_one("#add-source-name", Input).value.strip()
        self.query_one("#add-source", Button).disabled = (
            self.selected_path is None or not name
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Confirm the source or cancel without changing the config."""
        if event.button.id == "cancel-source":
            self.dismiss(None)
        elif event.button.id == "add-source" and self.selected_path is not None:
            recursive = self.query_one("#add-source-recursive", Checkbox).value
            name = self.query_one("#add-source-name", Input).value.strip()
            if name:
                self.dismiss(AddSourceSelection(self.selected_path, recursive, name))

    def action_cancel(self) -> None:
        """Close the picker without saving anything."""
        self.dismiss(None)


class RenameSourceScreen(ModalScreen[str | None]):
    """Ask for a replacement display name for a configured source."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
    ]

    def __init__(self, current_name: str):
        super().__init__()
        self.current_name = current_name

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Rename source", id="rename-source-title"),
            Input(value=self.current_name, id="rename-source-name"),
            Horizontal(
                Button("Save", id="rename-source-save", variant="primary"),
                Button("Cancel", id="cancel-rename-source"),
                id="rename-source-actions",
            ),
            id="rename-source-dialog",
        )

    def on_mount(self) -> None:
        """Focus the name so typing immediately replaces the old name."""
        name_input = self.query_one("#rename-source-name", Input)
        name_input.focus()
        name_input.select_all()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Save a non-empty name or cancel without changing the config."""
        if event.button.id == "cancel-rename-source":
            self.dismiss(None)
        elif event.button.id == "rename-source-save":
            name = self.query_one("#rename-source-name", Input).value.strip()
            if name:
                self.dismiss(name)

    def action_cancel(self) -> None:
        """Close the rename dialog without saving anything."""
        self.dismiss(None)
