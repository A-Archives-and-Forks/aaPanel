# coding: utf-8

import os
import signal
import sys


PANEL_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for candidate in (PANEL_PATH, os.path.join(PANEL_PATH, "class"), os.path.join(PANEL_PATH, "class_v2")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from mod.project.project_import.core.constants import TASK_CANCELLED, TASK_FAILED, TASK_SUCCESS
from mod.project.project_import.core.exceptions import ImportTaskCancelled, ProjectImportError
from mod.project.project_import.core.executor import execute_task
from mod.project.project_import.core.session_store import SessionStore
from mod.project.project_import.core.task_store import TaskStore


ACTIVE_TASK_ID = ""


def _signal_handler(_signum, _frame):
    if ACTIVE_TASK_ID:
        try:
            TaskStore().request_cancel(ACTIVE_TASK_ID)
        except Exception:
            pass


def _restore_session_after_terminal_error(task_id, message, error_code):
    try:
        store = TaskStore()
        task = store.get(task_id)
        task_type = task.get("task_type")
        if task_type == "analysis":
            task_field = "analysis_task_id"
            active_status = "analyzing"
            restored_status = "created"
        elif task_type == "import":
            task_field = "import_task_id"
            active_status = "importing"
            restored_status = "analyzed"
        else:
            return

        session_id = task.get("session_id", "")

        def restore(data):
            if data.get(task_field) != task_id or data.get("status") != active_status:
                return data
            data["status"] = restored_status
            data["last_task_error"] = {
                "task_id": task_id,
                "task_type": task_type,
                "error": str(message),
                "error_code": str(error_code),
            }
            return data

        SessionStore().update(session_id, restore)
    except Exception:
        pass


def main(task_id):
    global ACTIVE_TASK_ID
    ACTIVE_TASK_ID = task_id
    store = TaskStore()
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    try:
        task = store.get(task_id)
        if task.get("status") in (TASK_SUCCESS, TASK_FAILED, TASK_CANCELLED):
            return 0
        store.set_process(task_id, os.getpid(), os.getpgrp() if hasattr(os, "getpgrp") else os.getpid())
        store.set_running(task_id)
        execute_task(task_id)
        return 0
    except ImportTaskCancelled as exc:
        store.set_cancelled(task_id, str(exc))
        _restore_session_after_terminal_error(task_id, str(exc), "TASK_CANCELLED")
        return 2
    except ProjectImportError as exc:
        store.set_failed(task_id, str(exc), exc.code)
        _restore_session_after_terminal_error(task_id, str(exc), exc.code)
        return 1
    except Exception as exc:
        import traceback
        traceback.print_exc()
        store.set_failed(task_id, str(exc), "UNEXPECTED_ERROR")
        _restore_session_after_terminal_error(task_id, str(exc), "UNEXPECTED_ERROR")
        return 1
    finally:
        store.delete_secret(task_id)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: service.py <task_id>")
    raise SystemExit(main(sys.argv[1]))
