from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from dsxa_sdk_py import DSXAClient
from textual import events
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Footer, Header, Input, Label, Static, TextArea


class PathPickerScreen(ModalScreen[Optional[str]]):
    CSS = """
    PathPickerScreen {
        align: center middle;
    }

    #picker {
        width: 90%;
        height: 85%;
        border: round $accent;
        background: $surface;
        padding: 1;
    }

    #picker_title {
        text-style: bold;
        margin-bottom: 1;
    }

    #picker_tree {
        height: 1fr;
        border: solid $panel;
    }

    #picker_help {
        margin-top: 1;
        color: $text-muted;
    }
    """

    def __init__(self, mode: str = "file", start_path: Optional[str] = None) -> None:
        super().__init__()
        self.mode = mode
        if start_path:
            expanded = Path(start_path).expanduser()
            if expanded.exists():
                root = expanded if expanded.is_dir() else expanded.parent
            else:
                root = Path.home()
        else:
            root = Path.home()
        self.root_path = root

    def compose(self) -> ComposeResult:
        title = "Pick File" if self.mode == "file" else "Pick Folder"
        with Vertical(id="picker"):
            yield Label(title, id="picker_title")
            yield DirectoryTree(str(self.root_path), id="picker_tree")
            yield Label("Enter: select  Esc: cancel", id="picker_help")

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        if self.mode != "file":
            return
        self.dismiss(str(event.path))

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        if self.mode != "dir":
            return
        self.dismiss(str(event.path))


class DSXATuiApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #main {
        height: 1fr;
    }

    #left {
        width: 48;
        min-width: 40;
        padding: 1;
        border: solid $panel;
    }

    #right {
        width: 1fr;
        padding: 1;
        border: solid $panel;
    }

    Label {
        margin-top: 1;
    }

    Input {
        width: 1fr;
    }

    #actions {
        margin-top: 1;
        height: auto;
    }

    Button {
        margin-right: 1;
        margin-top: 1;
    }

    #status {
        margin-top: 1;
        color: $success;
    }

    #output {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+l", "clear_output", "Clear Output"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Label("Scanner Base URL")
                yield Input(value="http://127.0.0.1:15000", id="base_url")

                yield Label("Auth Token (optional)")
                yield Input(placeholder="AUTH_TOKEN", password=True, id="auth_token")

                yield Label("Protected Entity")
                yield Input(value="1", id="protected_entity")

                yield Label("Verify TLS (true/false)")
                yield Input(value="false", id="verify_tls")

                yield Label("File Path")
                yield Input(placeholder="/path/to/file", id="file_path")
                with Horizontal():
                    yield Button("Pick File", id="pick_file")
                    yield Button("Pick Folder", id="pick_folder")

                yield Label("SHA256 Hash")
                yield Input(placeholder="hash value", id="hash_value")

                with Horizontal(id="actions"):
                    yield Button("Scan File", id="scan_file", variant="primary")
                    yield Button("Scan Hash", id="scan_hash")

                yield Static("Ready", id="status")

            with Vertical(id="right"):
                yield Label("Output")
                yield TextArea(id="output", read_only=True)

        yield Footer()

    def action_clear_output(self) -> None:
        self.query_one("#output", TextArea).text = ""

    def _set_status(self, message: str, error: bool = False) -> None:
        status = self.query_one("#status", Static)
        status.update(message)
        status.styles.color = "red" if error else "green"

    def _append_output(self, text: str) -> None:
        output = self.query_one("#output", TextArea)
        existing = output.text
        if existing:
            output.text = f"{existing}\n\n{text}"
        else:
            output.text = text

    def _shorten_home(self, p: Path) -> str:
        try:
            home = Path.home().resolve()
            resolved = p.resolve()
            if resolved == home or home in resolved.parents:
                rel = resolved.relative_to(home)
                return f"~/{rel}" if str(rel) != "." else "~"
        except Exception:
            pass
        return str(p)

    def _complete_path(self, raw_value: str) -> tuple[str | None, str]:
        value = raw_value.strip()
        if not value:
            value = "."

        expanded = Path(value).expanduser()
        has_trailing_sep = raw_value.endswith(os.sep)
        parent = expanded if has_trailing_sep else (expanded.parent if str(expanded.parent) else Path("."))
        prefix = "" if has_trailing_sep else expanded.name

        try:
            if not parent.exists() or not parent.is_dir():
                return None, "Path parent does not exist"
            matches = sorted(parent.glob(f"{prefix}*"), key=lambda p: p.name.lower())
        except Exception as exc:
            return None, f"Completion error: {exc}"

        if not matches:
            return None, "No completion matches"

        if len(matches) == 1:
            target = matches[0]
            completed = self._shorten_home(target)
            if target.is_dir() and not completed.endswith(os.sep):
                completed += os.sep
            return completed, f"Completed: {target.name}"

        names = [m.name for m in matches]
        common = os.path.commonprefix(names)
        if common and common != prefix:
            completed = parent / common
            return self._shorten_home(completed), f"Matched {len(matches)} paths"

        preview = ", ".join(names[:5])
        more = " ..." if len(names) > 5 else ""
        return None, f"Matches: {preview}{more}"

    def _client(self) -> DSXAClient:
        base_url = self.query_one("#base_url", Input).value.strip()
        auth_token = self.query_one("#auth_token", Input).value.strip() or None
        verify_tls_raw = self.query_one("#verify_tls", Input).value.strip().lower()
        verify_tls = verify_tls_raw in {"1", "true", "yes", "y", "on"}

        pe_raw = self.query_one("#protected_entity", Input).value.strip()
        try:
            protected_entity: Optional[int] = int(pe_raw) if pe_raw else 1
        except ValueError as exc:
            raise ValueError("Protected Entity must be an integer") from exc

        return DSXAClient(
            base_url=base_url,
            auth_token=auth_token,
            default_protected_entity=protected_entity,
            verify_tls=verify_tls,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "scan_file":
            self.scan_file()
        elif event.button.id == "scan_hash":
            self.scan_hash()
        elif event.button.id == "pick_file":
            self._open_path_picker("file")
        elif event.button.id == "pick_folder":
            self._open_path_picker("dir")

    def _open_path_picker(self, mode: str) -> None:
        current = self.query_one("#file_path", Input).value.strip()

        def _on_pick(result: Optional[str]) -> None:
            if not result:
                self._set_status("Path selection canceled", error=False)
                return
            value = result
            if mode == "dir" and not value.endswith(os.sep):
                value = f"{value}{os.sep}"
            self.query_one("#file_path", Input).value = value
            self._set_status(f"Selected: {value}", error=False)

        self.push_screen(PathPickerScreen(mode=mode, start_path=current), _on_pick)

    def on_key(self, event: events.Key) -> None:
        if event.key != "tab":
            return
        focused = self.focused
        if not isinstance(focused, Input):
            return
        if focused.id != "file_path":
            return

        completed, message = self._complete_path(focused.value)
        if completed is not None:
            focused.value = completed
        self._set_status(message, error=completed is None)
        event.stop()
        event.prevent_default()

    @work(thread=True)
    def scan_file(self) -> None:
        path_raw = self.query_one("#file_path", Input).value.strip()
        if not path_raw:
            self.call_from_thread(self._set_status, "File path is required", True)
            return

        path = Path(path_raw)
        if not path.exists() or not path.is_file():
            self.call_from_thread(self._set_status, f"Invalid file path: {path}", True)
            return

        self.call_from_thread(self._set_status, f"Scanning file: {path.name} ...", False)

        try:
            client = self._client()
            with path.open("rb") as fh:
                response = client.scan_binary_stream(iter(lambda: fh.read(1024 * 1024), b""))
            client.close()
            payload = json.dumps(response.model_dump(mode="json"), indent=2)
            self.call_from_thread(self._append_output, f"Scan File Result\n{payload}")
            self.call_from_thread(self._set_status, "Scan file complete", False)
        except Exception as exc:
            self.call_from_thread(self._append_output, f"Scan File Error\n{exc}")
            self.call_from_thread(self._set_status, "Scan file failed", True)

    @work(thread=True)
    def scan_hash(self) -> None:
        hash_value = self.query_one("#hash_value", Input).value.strip()
        if not hash_value:
            self.call_from_thread(self._set_status, "Hash value is required", True)
            return

        self.call_from_thread(self._set_status, "Scanning hash ...", False)

        try:
            client = self._client()
            response = client.scan_hash(hash_value)
            client.close()
            payload = json.dumps(response.model_dump(mode="json"), indent=2)
            self.call_from_thread(self._append_output, f"Scan Hash Result\n{payload}")
            self.call_from_thread(self._set_status, "Scan hash complete", False)
        except Exception as exc:
            self.call_from_thread(self._append_output, f"Scan Hash Error\n{exc}")
            self.call_from_thread(self._set_status, "Scan hash failed", True)


def run() -> None:
    DSXATuiApp().run()


if __name__ == "__main__":
    run()
