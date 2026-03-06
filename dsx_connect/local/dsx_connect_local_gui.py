#!/usr/bin/env python3
"""Simple GUI wrapper for DSX-Connect local runtime manager."""

from __future__ import annotations

import queue
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, Button, Entry, Frame, Label, Scrollbar, StringVar, Text, Tk, ttk

import dsx_connect.local.dsx_connect_local as manager


class LocalGui:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("DSX-Connect Local")
        self.root.geometry("980x640")

        self.state_dir_var = StringVar(value=str(manager.DEFAULT_STATE_DIR))
        self.redis_port_var = StringVar(value=str(manager.DEFAULT_REDIS_PORT))
        self.status_var = StringVar(value="idle")
        self.msg_var = StringVar(value="")

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
        Entry(top, textvariable=self.state_dir_var, width=62).pack(side=LEFT, padx=(6, 14))

        Label(top, text="Redis Port:").pack(side=LEFT)
        Entry(top, textvariable=self.redis_port_var, width=8).pack(side=LEFT, padx=(6, 14))

        Button(top, text="Open UI", command=self.open_ui).pack(side=RIGHT)

        actions = Frame(self.root)
        actions.pack(fill="x", padx=10)

        Button(actions, text="Init", command=self.init_state).pack(side=LEFT)
        Button(actions, text="Start", command=self.start_stack).pack(side=LEFT, padx=(8, 0))
        Button(actions, text="Stop", command=self.stop_stack).pack(side=LEFT, padx=(8, 0))
        Button(actions, text="Refresh", command=self.refresh_all).pack(side=LEFT, padx=(8, 0))
        Button(actions, text="Quit", command=self.quit_app).pack(side=LEFT, padx=(8, 0))

        Label(actions, textvariable=self.status_var).pack(side=LEFT, padx=(16, 0))

        msg = Label(self.root, textvariable=self.msg_var, anchor="w")
        msg.pack(fill="x", padx=10, pady=(6, 6))

        table = Frame(self.root)
        table.pack(fill="x", padx=10)

        self.tree = ttk.Treeview(table, columns=("service", "state", "pid", "log"), show="headings", height=4)
        for col, width in (("service", 120), ("state", 100), ("pid", 100), ("log", 620)):
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

    def _ctx(self) -> tuple[Path, int]:
        state_dir = Path(self.state_dir_var.get()).expanduser()
        redis_port = int(self.redis_port_var.get())
        return state_dir, redis_port

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

    def init_state(self) -> None:
        def op() -> None:
            state_dir, redis_port = self._ctx()
            paths = manager._ensure_dirs(state_dir)
            env_file = paths["env"]
            if not env_file.exists():
                env_file.write_text(manager._default_env_template(redis_port))
                self._append_msg(f"initialized: {env_file}")
            else:
                self._append_msg(f"env exists: {env_file}")

        self._run_bg(op, "init")

    def start_stack(self) -> None:
        def op() -> None:
            state_dir, redis_port = self._ctx()
            paths = manager._ensure_dirs(state_dir)
            env_path = paths["env"]
            if not env_path.exists():
                env_path.write_text(manager._default_env_template(redis_port))

            specs = manager._service_specs(state_dir, redis_port)
            child_env = manager._child_env(env_path)

            for svc in manager.SERVICE_ORDER:
                spec = specs[svc]
                pid = manager._pid_from_file(spec.pidfile)
                if manager._is_pid_alive(pid):
                    self._append_msg(f"{svc}: already running ({pid})")
                    continue
                if svc == "redis" and manager._redis_server_binary() is None:
                    raise RuntimeError("redis-server not found")

                pid = manager._spawn(spec, child_env)
                if not manager._wait_for_pid(pid):
                    raise RuntimeError(f"{svc}: failed to start")
                time.sleep(0.6)
                if not manager._is_pid_alive(pid):
                    raise RuntimeError(f"{svc}: exited during startup")
                manager._write_pid(spec.pidfile, pid)
                self._append_msg(f"{svc}: started pid={pid}")

        self._run_bg(op, "start")

    def stop_stack(self) -> None:
        def op() -> None:
            state_dir, redis_port = self._ctx()
            specs = manager._service_specs(state_dir, redis_port)
            for svc in reversed(manager.SERVICE_ORDER):
                spec = specs[svc]
                pid = manager._pid_from_file(spec.pidfile)
                if not manager._is_pid_alive(pid):
                    manager._remove_pid(spec.pidfile)
                    self._append_msg(f"{svc}: not running")
                    continue
                manager._terminate_pid(pid, grace_seconds=8.0)
                manager._remove_pid(spec.pidfile)
                self._append_msg(f"{svc}: stopped")

        self._run_bg(op, "stop")

    def refresh_all(self) -> None:
        state_dir, redis_port = self._ctx()
        specs = manager._service_specs(state_dir, redis_port)

        for item in self.tree.get_children():
            self.tree.delete(item)

        for svc in manager.SERVICE_ORDER:
            spec = specs[svc]
            pid = manager._pid_from_file(spec.pidfile)
            alive = manager._is_pid_alive(pid)
            self.tree.insert("", END, values=(svc, "running" if alive else "stopped", pid or "-", str(spec.logfile)))

    def _refresh_live_log(self) -> None:
        state_dir, _ = self._ctx()
        log_file = state_dir / "logs" / "api.log"
        if not log_file.exists():
            return

        try:
            content = log_file.read_text(errors="replace")
        except Exception:
            return

        size = len(content)
        if size == self._last_log_size:
            return

        if size < self._last_log_size:
            self.text.delete("1.0", END)

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
        self.root.after(1200, self._tick)

    def quit_app(self) -> None:
        def op() -> None:
            state_dir, redis_port = self._ctx()
            specs = manager._service_specs(state_dir, redis_port)
            for svc in reversed(manager.SERVICE_ORDER):
                spec = specs[svc]
                pid = manager._pid_from_file(spec.pidfile)
                if not manager._is_pid_alive(pid):
                    manager._remove_pid(spec.pidfile)
                    continue
                manager._terminate_pid(pid, grace_seconds=8.0)
                manager._remove_pid(spec.pidfile)

            self._queue.put("__QUIT__")

        self._run_bg(op, "quit")

    def open_ui(self) -> None:
        webbrowser.open("http://127.0.0.1:8586")

    def run(self) -> None:
        self.refresh_all()
        self.root.mainloop()


def main() -> None:
    LocalGui().run()


if __name__ == "__main__":
    main()
