#!/usr/bin/env python3
"""Reusable Tk GUI for single-service connector local runtime managers."""

from __future__ import annotations

import queue
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, Button, Entry, Frame, Label, Scrollbar, StringVar, Text, Tk, ttk


class SingleServiceLocalGui:
    def __init__(
        self,
        *,
        manager,
        title: str,
        state_dir: Path,
        port: int,
        open_url: str = "http://127.0.0.1:8586",
        default_host: str = "0.0.0.0",
        poll_ms: int = 1200,
        env_fields: list[tuple[str, str, bool]] | None = None,
        require_init_before_start: bool = False,
        env_edit_dev_only: bool = False,
    ) -> None:
        self.manager = manager
        self.open_url = open_url
        self.default_host = default_host
        self.poll_ms = poll_ms
        self.env_fields = env_fields or []
        self.require_init_before_start = require_init_before_start
        self.env_edit_dev_only = env_edit_dev_only

        self.root = Tk()
        self.root.title(title)
        self.root.geometry("980x700")

        self.state_dir_var = StringVar(value=str(state_dir))
        self.port_var = StringVar(value=str(port))
        self.host_var = StringVar(value=default_host)

        self.status_var = StringVar(value="idle")
        self.msg_var = StringVar(value="")
        self.init_hint_var = StringVar(value="")

        self._worker_busy = False
        self._queue: queue.Queue[str] = queue.Queue()
        self._last_log_size = 0
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)
        self._tick()

    def _build_ui(self) -> None:
        top = Frame(self.root)
        top.pack(fill="x", padx=10, pady=10)

        Label(top, text="State Dir:").pack(side=LEFT)
        Entry(top, textvariable=self.state_dir_var, width=56).pack(side=LEFT, padx=(6, 10))

        Label(top, text="Port:").pack(side=LEFT)
        Entry(top, textvariable=self.port_var, width=7).pack(side=LEFT, padx=(6, 10))

        Label(top, text="Host:").pack(side=LEFT)
        Entry(top, textvariable=self.host_var, width=10).pack(side=LEFT, padx=(6, 10))

        Button(top, text="Open DSX UI", command=self.open_ui).pack(side=RIGHT)

        actions = Frame(self.root)
        actions.pack(fill="x", padx=10)

        self.init_btn = Button(actions, text="Init", command=self.init_state)
        self.init_btn.pack(side=LEFT)
        self.start_btn = Button(actions, text="Start", command=self.start_connector)
        self.start_btn.pack(side=LEFT, padx=(8, 0))
        self.stop_btn = Button(actions, text="Stop", command=self.stop_connector)
        self.stop_btn.pack(side=LEFT, padx=(8, 0))
        self.refresh_btn = Button(actions, text="Refresh", command=self.refresh_all)
        self.refresh_btn.pack(side=LEFT, padx=(8, 0))
        self.quit_btn = Button(actions, text="Quit", command=self.quit_app)
        self.quit_btn.pack(side=LEFT, padx=(8, 0))

        Label(actions, textvariable=self.status_var).pack(side=LEFT, padx=(16, 0))

        hint = Label(self.root, textvariable=self.init_hint_var, anchor="w")
        hint.pack(fill="x", padx=10, pady=(4, 2))

        msg = Label(self.root, textvariable=self.msg_var, anchor="w")
        msg.pack(fill="x", padx=10, pady=(6, 6))

        table = Frame(self.root)
        table.pack(fill="x", padx=10)

        self.tree = ttk.Treeview(table, columns=("service", "state", "pid", "log"), show="headings", height=3)
        for col, width in (("service", 200), ("state", 100), ("pid", 100), ("log", 560)):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="x")

        logs = Frame(self.root)
        logs.pack(fill=BOTH, expand=True, padx=10, pady=(8, 10))

        self.text = Text(logs, wrap="none")
        self.text.pack(side=LEFT, fill=BOTH, expand=True)

        scroll = Scrollbar(logs, orient=VERTICAL, command=self.text.yview)
        scroll.pack(side=RIGHT, fill="y")
        self.text.configure(yscrollcommand=scroll.set)

    def _ctx(self) -> tuple[Path, int, str]:
        state_dir = Path(self.state_dir_var.get()).expanduser()
        port = int(self.port_var.get())
        host = self.host_var.get().strip() or self.default_host
        return state_dir, port, host

    def _append_msg(self, message: str) -> None:
        self.msg_var.set(message)
        self._queue.put(message)

    def _run_bg(self, fn, label: str) -> None:
        if self._worker_busy:
            self._append_msg("busy")
            return

        def task() -> None:
            self._worker_busy = True
            self.status_var.set(label)
            try:
                fn()
            except Exception as exc:
                self._append_msg(f"error: {exc}")
            finally:
                self._worker_busy = False
                self.status_var.set("idle")
                self.refresh_all()

        threading.Thread(target=task, daemon=True).start()

    def _env_path(self) -> Path:
        state_dir, _, _ = self._ctx()
        return state_dir / ".env.local"

    @staticmethod
    def _read_env_map(path: Path) -> dict[str, str]:
        out: dict[str, str] = {}
        if not path.exists():
            return out
        for line in path.read_text(errors="replace").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            out[k.strip()] = v.strip()
        return out

    @staticmethod
    def _upsert_env_values(path: Path, values: dict[str, str]) -> None:
        existing_lines = path.read_text(errors="replace").splitlines() if path.exists() else []
        keys = set(values.keys())
        written: set[str] = set()
        new_lines: list[str] = []

        for line in existing_lines:
            s = line.strip()
            if not s or s.startswith("#") or "=" not in line:
                new_lines.append(line)
                continue
            k, _ = line.split("=", 1)
            key = k.strip()
            if key in keys:
                new_lines.append(f"{key}={values[key]}")
                written.add(key)
            else:
                new_lines.append(line)

        for key in keys:
            if key not in written:
                new_lines.append(f"{key}={values[key]}")

        if new_lines and new_lines[-1] != "":
            new_lines.append("")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(new_lines))

    def _refresh_init_state_ui(self) -> None:
        env_exists = self._env_path().exists()
        if self.require_init_before_start and not env_exists:
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="disabled")
            self.init_hint_var.set("Init required: click Init to create .env.local before Start/Stop.")
        else:
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="normal")
            self.init_hint_var.set("")

    def init_state(self) -> None:
        def op() -> None:
            state_dir, port, _ = self._ctx()
            paths = self.manager._ensure_dirs(state_dir)
            env_file = paths["env"]
            if not env_file.exists():
                env_file.write_text(self.manager._default_env_template(state_dir=state_dir, port=port))
                self._append_msg(f"initialized: {env_file}")
            else:
                self._append_msg(f"env exists: {env_file}")

        self._run_bg(op, "init")

    def _spec(self):
        state_dir, port, _ = self._ctx()
        return self.manager._service_spec(state_dir, port=port, host=self.default_host, workers=1, reload=False)

    def start_connector(self) -> None:
        def op() -> None:
            state_dir, port, host = self._ctx()
            paths = self.manager._ensure_dirs(state_dir)
            env_path = paths["env"]
            if self.require_init_before_start and not env_path.exists():
                self._append_msg("Init required: click Init before Start.")
                return
            if not env_path.exists():
                env_path.write_text(self.manager._default_env_template(state_dir=state_dir, port=port))

            spec = self.manager._service_spec(state_dir, port=port, host=host, workers=1, reload=False)
            pid = self.manager._pid_from_file(spec.pidfile)
            if self.manager._is_pid_alive(pid):
                self._append_msg(f"{spec.name}: already running ({pid})")
                return

            child_env = self.manager._child_env(env_path)
            with spec.logfile.open("ab") as log_fp:
                proc = self.manager.subprocess.Popen(
                    spec.command,
                    cwd=spec.cwd,
                    env=child_env,
                    stdout=log_fp,
                    stderr=self.manager.subprocess.STDOUT,
                    start_new_session=True,
                )

            pid = proc.pid
            if not self.manager._wait_for_pid(pid):
                raise RuntimeError(f"{spec.name}: failed to start")
            time.sleep(0.6)
            if not self.manager._is_pid_alive(pid):
                raise RuntimeError(f"{spec.name}: exited during startup")
            self.manager._write_pid(spec.pidfile, pid)
            self._append_msg(f"{spec.name}: started pid={pid}")

        self._run_bg(op, "start")

    def stop_connector(self) -> None:
        def op() -> None:
            spec = self._spec()
            pid = self.manager._pid_from_file(spec.pidfile)
            if not self.manager._is_pid_alive(pid):
                self.manager._remove_pid(spec.pidfile)
                self._append_msg(f"{spec.name}: not running")
                return
            self.manager._terminate_pid(pid, grace_seconds=8.0)
            self.manager._remove_pid(spec.pidfile)
            self._append_msg(f"{spec.name}: stopped")

        self._run_bg(op, "stop")

    def quit_app(self) -> None:
        def op() -> None:
            spec = self._spec()
            pid = self.manager._pid_from_file(spec.pidfile)
            if self.manager._is_pid_alive(pid):
                self.manager._terminate_pid(pid, grace_seconds=8.0)
                self.manager._remove_pid(spec.pidfile)
            self._queue.put("__QUIT__")

        self._run_bg(op, "quit")

    def refresh_all(self) -> None:
        spec = self._spec()

        for item in self.tree.get_children():
            self.tree.delete(item)

        pid = self.manager._pid_from_file(spec.pidfile)
        alive = self.manager._is_pid_alive(pid)
        self.tree.insert("", END, values=(spec.name, "running" if alive else "stopped", pid or "-", str(spec.logfile)))
        self._refresh_init_state_ui()

    def _refresh_live_log(self) -> None:
        log_file = self._spec().logfile
        if not log_file.exists():
            return

        try:
            content = log_file.read_text(errors="replace")
        except Exception:
            return

        size = len(content)
        if size == self._last_log_size:
            return

        self.text.delete("1.0", END)
        self.text.insert(END, "\n".join(content.splitlines()[-400:]))
        self.text.see(END)
        self._last_log_size = size

    def _drain_queue(self) -> None:
        drained = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if drained:
            if "__QUIT__" in drained:
                self.root.after(100, self.root.destroy)
                return
            self.msg_var.set(drained[-1])

    def _tick(self) -> None:
        self._drain_queue()
        self.refresh_all()
        self._refresh_live_log()
        self.root.after(self.poll_ms, self._tick)

    def open_ui(self) -> None:
        webbrowser.open(self.open_url)

    def run(self) -> None:
        self.refresh_all()
        self.root.mainloop()
