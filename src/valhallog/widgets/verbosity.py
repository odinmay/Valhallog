"""A Select control with the application's vim-style menu navigation."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.widgets import Select
from textual.widgets._select import SelectCurrent, SelectOverlay


class VimSelectOverlay(SelectOverlay):
    """Allow j/k to move and l to confirm inside a Select menu."""

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "j":
            self.action_cursor_down()
            event.stop()
            event.prevent_default()
            return
        if event.key == "k":
            self.action_cursor_up()
            event.stop()
            event.prevent_default()
            return
        if event.key == "l":
            self.action_select()
            event.stop()
            event.prevent_default()
            return
        await super()._on_key(event)


class VerbositySelectCurrent(SelectCurrent):
    """Display the verbosity mnemonic inside the Select button."""

    def update(self, label) -> None:
        if isinstance(label, str) and label is not Select.NULL:
            label = f"(V)ERBOSITY {label}"
        super().update(label)


class VimVerbositySelect(Select[str]):
    """A level selector whose button and overlay use Valhallog conventions."""

    def compose(self) -> ComposeResult:
        yield VerbositySelectCurrent(self.prompt)
        yield VimSelectOverlay(type_to_search=self._type_to_search).data_bind(
            compact=Select.compact
        )
