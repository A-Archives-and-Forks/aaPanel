# coding: utf-8

import contextlib
import json
import os
import tempfile
import threading

from .constants import ensure_runtime_dirs
from .exceptions import ProjectImportError


_PROCESS_LOCK = threading.RLock()


@contextlib.contextmanager
def file_lock(lock_path):
    """Cross-process advisory lock on Linux, process lock elsewhere."""
    ensure_runtime_dirs()
    os.makedirs(os.path.dirname(lock_path), mode=0o700, exist_ok=True)
    with _PROCESS_LOCK:
        handle = open(lock_path, "a+", encoding="utf-8")
        try:
            try:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            yield
        finally:
            try:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            handle.close()


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (OSError, ValueError, TypeError) as exc:
        raise ProjectImportError("Invalid state file: {}".format(exc), "STATE_FILE_INVALID")


def atomic_write_json(path, data, mode=0o600):
    ensure_runtime_dirs()
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".project_import_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp_path, mode)
        except OSError:
            pass
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

