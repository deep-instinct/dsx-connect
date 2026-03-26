from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from dsxa_sdk_py import DSXAClient
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, Static, TextArea


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
