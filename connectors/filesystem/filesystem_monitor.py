import threading
from abc import ABC, abstractmethod

import pathlib
from shared.dsx_logging import dsx_logging
from shared.file_ops import path_matches_filter
try:
    from watchfiles import watch, Change  # type: ignore
    _HAVE_WATCHFILES = True
except Exception:
    watch = None  # type: ignore
    Change = None  # type: ignore
    _HAVE_WATCHFILES = False


class FilesystemMonitorCallback(ABC):
    @abstractmethod
    def file_modified_callback(self, file_path: pathlib.Path):
        pass


class FilesystemMonitor:

    def __init__(self, folder: pathlib.Path, filter: str, callback: FilesystemMonitorCallback,
                 force_polling: bool = False, poll_interval_ms: int = 1000,
                 ignore_paths: list[pathlib.Path] | None = None):
        self._folder = folder
        self._filter = filter or ""
        self._callback = callback
        self._shutdown_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._force_polling = force_polling
        self._poll_interval_ms = max(10, int(poll_interval_ms or 1000))
        self._ignore_rel: list[str] = []
        self._ignore_abs: list[str] = []
        for p in ignore_paths or []:
            try:
                resolved = p.expanduser().resolve()
            except Exception:
                resolved = p
            self._ignore_abs.append(resolved.as_posix())
            try:
                rel = resolved.relative_to(self._folder)
                self._ignore_rel.append(rel.as_posix())
            except Exception:
                pass

    def start(self):
        if not _HAVE_WATCHFILES:
            dsx_logging.warning("watchfiles not installed; FilesystemMonitor.start will be a no-op.")
            return
        if self._thread and self._thread.is_alive():
            dsx_logging.debug("FilesystemMonitor already running")
            return
        if self._shutdown_event.is_set():
            self._shutdown_event.clear()

        def _run():
            if self._force_polling:
                # Configure watchfiles via env for portability across versions
                import os
                os.environ["WATCHFILES_FORCE_POLLING"] = "1"
                # watchfiles expects seconds (float) for WATCHFILES_POLL_DELAY
                delay_s = str(self._poll_interval_ms / 1000.0)
                os.environ["WATCHFILES_POLL_DELAY"] = delay_s
                dsx_logging.debug(
                    f"Starting watchfiles (polling) on {self._folder} with filter='{self._filter}', interval={delay_s}s")
            else:
                dsx_logging.debug(
                    f"Starting watchfiles on {self._folder} with filter='{self._filter}'")
            try:
                # Build a watchfiles filter that screens non-matching files early
                def _watch_filter(change, path_str: str) -> bool:  # type: ignore[override]
                    try:
                        pth = pathlib.Path(path_str)
                        # Only consider regular files
                        if not pth.exists() or not pth.is_file():
                            return False
                        resolved = pth.resolve()
                        rel_posix = None
                        try:
                            rel = resolved.relative_to(self._folder)
                            rel_posix = rel.as_posix()
                        except Exception:
                            pass
                        if rel_posix:
                            for ignore in self._ignore_rel:
                                if rel_posix == ignore or rel_posix.startswith(ignore.rstrip('/') + '/'):
                                    return False
                        abs_posix = resolved.as_posix()
                        if any(abs_posix == ignore or abs_posix.startswith(ignore.rstrip('/') + '/')
                               for ignore in self._ignore_abs):
                            return False
                        return path_matches_filter(self._folder, pth, self._filter)
                    except Exception:
                        return False

                for changes in watch(
                    self._folder,
                    recursive=True,
                    debounce=500,
                    watch_filter=_watch_filter,
                    stop_event=self._shutdown_event,
                ):
                    if self._shutdown_event.is_set():
                        break
                    for change, path_str in changes:
                        # Only handle file creations/modifications
                        if change not in (Change.added, Change.modified):
                            continue
                        p = pathlib.Path(path_str)
                        if not p.exists() or not p.is_file():
                            continue
                        resolved = p.resolve()
                        ignore_hit = False
                        try:
                            rel = resolved.relative_to(self._folder)
                            rel_posix = rel.as_posix()
                            if any(rel_posix == ignore or rel_posix.startswith(ignore.rstrip('/') + '/')
                                   for ignore in self._ignore_rel):
                                ignore_hit = True
                        except Exception:
                            pass
                        abs_posix = resolved.as_posix()
                        if any(abs_posix == ignore or abs_posix.startswith(ignore.rstrip('/') + '/')
                               for ignore in self._ignore_abs):
                            ignore_hit = True
                        if ignore_hit:
                            dsx_logging.debug(f"File {p} ignored by monitor (ignore list)")
                            continue
                        # Apply rsync-like filter as an extra guard
                        if not path_matches_filter(self._folder, p, self._filter):
                            dsx_logging.debug(f"File {p} ignored by filter '{self._filter}'")
                            continue
                        # Try to ensure file is readable (handles in-progress writes)
                        try:
                            with p.open('rb') as f:
                                _ = f.read(1)
                        except FileNotFoundError as e:
                            dsx_logging.warning(f'File {p} not found during event handling: {e}')
                            continue
                        except Exception as e:
                            dsx_logging.debug(f'File {p} not ready to open: {e}')
                            continue

                        dsx_logging.debug(f'New or modified file detected: {p}')
                        if not self._shutdown_event.is_set():
                            try:
                                self._callback.file_modified_callback(file_path=p)
                            except Exception as e:
                                dsx_logging.error(f"Error in file callback: {e}")
            except Exception as e:
                dsx_logging.error(f"watchfiles loop error: {e}")

        self._thread = threading.Thread(target=_run, name="filesystem-monitor", daemon=True)
        self._thread.start()

    def stop(self):
        self._shutdown_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10.0)
            if self._thread.is_alive():
                dsx_logging.warning("Filesystem monitor thread did not shut down cleanly within timeout")
        self._thread = None
        dsx_logging.info("FilesystemMonitor stopped")

    # Backward-compatible helper for tests and direct triggering
    def on_modified(self, event):
        if self._shutdown_event.is_set():
            dsx_logging.debug("Ignoring file event - monitor is shutting down")
            return
        if getattr(event, 'is_directory', False):
            return
        filename = pathlib.Path(getattr(event, 'src_path', ''))
        if not filename:
            return
        try:
            resolved = filename.resolve()
        except Exception:
            resolved = filename
        rel_posix = None
        try:
            rel = resolved.relative_to(self._folder)
            rel_posix = rel.as_posix()
        except Exception:
            pass
        ignore_hit = False
        if rel_posix:
            if any(rel_posix == ignore or rel_posix.startswith(ignore.rstrip('/') + '/')
                   for ignore in self._ignore_rel):
                ignore_hit = True
        abs_posix = resolved.as_posix()
        if any(abs_posix == ignore or abs_posix.startswith(ignore.rstrip('/') + '/')
               for ignore in self._ignore_abs):
            ignore_hit = True
        if ignore_hit:
            dsx_logging.debug(f"File {filename} ignored by monitor (ignore list)")
            return
        try:
            if filename.exists() and filename.is_file():
                # Apply filter before attempting to open
                if not path_matches_filter(self._folder, filename, self._filter):
                    dsx_logging.debug(f"File {filename} ignored by filter '{self._filter}'")
                    return
                with filename.open('rb') as f:
                    _ = f.read(1)
        except FileNotFoundError as e:
            dsx_logging.warning(f'File {filename} not found: {e}')
            return
        except Exception as e:
            dsx_logging.debug(f'File {filename} not ready to open: {e}')
            return
        dsx_logging.debug(f'New or modified file detected: {filename}')
        if not self._shutdown_event.is_set():
            try:
                self._callback.file_modified_callback(file_path=filename)
            except Exception as e:
                dsx_logging.error(f"Error in file callback: {e}")
