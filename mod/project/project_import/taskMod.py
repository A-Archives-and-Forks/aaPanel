# coding: utf-8

import os
import signal
import subprocess
import sys

if "/www/server/panel" not in sys.path:
    sys.path.insert(0, "/www/server/panel")
if "/www/server/panel/class" not in sys.path:
    sys.path.insert(0, "/www/server/panel/class")
if "/www/server/panel/class_v2" not in sys.path:
    sys.path.insert(0, "/www/server/panel/class_v2")

import public

from mod.project.project_import.core.api_utils import error_response, parse_json_field
from mod.project.project_import.core.constants import (
    STEP_WAITING,
    TASK_CANCELLED,
    TASK_FAILED,
    TASK_QUEUED,
    TASK_RUNNING,
    logs_dir,
)
from mod.project.project_import.core.exceptions import ProjectImportError
from mod.project.project_import.core.session_store import SessionStore
from mod.project.project_import.core.task_store import TaskStore
from mod.project.project_import.sources.git import normalize_git_config


ANALYSIS_STEPS = [
    {"key": "validate_source", "title": "Validate project source", "status": STEP_WAITING},
    {"key": "fetch_source", "title": "Prepare project files", "status": STEP_WAITING},
    {"key": "detect_project", "title": "Analyze project type", "status": STEP_WAITING},
    {"key": "finalize", "title": "Save analysis result", "status": STEP_WAITING},
]

IMPORT_STEPS = [
    {"key": "preflight", "title": "Validate import settings", "status": STEP_WAITING},
    {"key": "runtime", "title": "Prepare project runtime", "status": STEP_WAITING},
    {"key": "commit_files", "title": "Commit project files", "status": STEP_WAITING},
    {"key": "create_project", "title": "Create aaPanel project", "status": STEP_WAITING},
    {"key": "database", "title": "Import database", "status": STEP_WAITING},
    {"key": "ssl", "title": "Configure SSL", "status": STEP_WAITING},
    {"key": "health", "title": "Check project health", "status": STEP_WAITING},
]


class main:
    def __init__(self):
        self.sessions = SessionStore()
        self.tasks = TaskStore()

    def start_analysis(self, get):
        try:
            session_id = str(get.get("session_id", "")).strip()
            source_type = str(get.get("source_type", "")).strip().lower()
            session = None
            if session_id:
                session = self.sessions.get(session_id)
                if source_type and source_type != session.get("source_type"):
                    raise ProjectImportError(
                        "source_type does not match the import session",
                        "SOURCE_TYPE_MISMATCH",
                    )
                source_type = str(session.get("source_type", "")).strip().lower()
            else:
                if not source_type:
                    raise ProjectImportError("source_type is required", "SOURCE_TYPE_REQUIRED")
                if source_type == "archive":
                    raise ProjectImportError(
                        "Archive analysis must use the session_id returned by upload",
                        "UPLOAD_SESSION_REQUIRED",
                    )
            source_config = parse_json_field(get.get("source_config", "{}"), "source_config")
            if not isinstance(source_config, dict):
                raise ProjectImportError("source_config must be a JSON object", "INVALID_SOURCE_CONFIG")
            if source_type == "git":
                source_config = normalize_git_config(source_config)
            if session is None:
                session = self.sessions.create(source_type)
                session_id = session["session_id"]
            self._ensure_task_inactive(session.get("analysis_task_id", ""))
            task = self.tasks.create(
                "analysis",
                session_id,
                ANALYSIS_STEPS,
                payload={"source_type": session.get("source_type", "")},
                secret={"source_config": source_config},
            )

            def update_session(data):
                data["status"] = "analyzing"
                data["analysis_task_id"] = task["task_id"]
                data["analysis"] = {}
                return data

            self.sessions.update(session_id, update_session)
            self._spawn(task["task_id"])
            if source_type:
                public.set_module_logs("project_import", "scan_project_{}".format(source_type))
            # 每次启动分析顺带清理上传区中长期残留的孤儿压缩包（> 会话 TTL 未消费）
            self.sessions.cleanup_upload_root()
            return public.return_message(0, 0, {
                "task_id": task["task_id"],
                "session_id": session_id,
            })
        except Exception as exc:
            return error_response(exc)

    def start_import(self, get):
        try:
            session_id = str(get.get("session_id", ""))
            session = self.sessions.get(session_id)
            self._ensure_task_inactive(session.get("import_task_id", ""))
            retryable_stale_import = (
                session.get("status") == "importing"
                and self._task_has_status(
                    session.get("import_task_id", ""),
                    (TASK_FAILED, TASK_CANCELLED),
                )
            )
            if session.get("status") != "analyzed" and not retryable_stale_import:
                raise ProjectImportError("Project analysis has not completed", "ANALYSIS_REQUIRED")
            project_config = parse_json_field(get.get("project_config", "{}"), "project_config")
            database_config = parse_json_field(get.get("database_config", "{}"), "database_config")
            if not isinstance(project_config, dict) or not isinstance(database_config, dict):
                raise ProjectImportError("Import configurations must be JSON objects", "INVALID_IMPORT_CONFIG")
            task = self.tasks.create(
                "import",
                session_id,
                IMPORT_STEPS,
                payload={"project_type": project_config.get("project_type", "")},
                secret={
                    "project_config": project_config,
                    "database_config": database_config,
                },
            )

            def update_session(data):
                data["status"] = "importing"
                data["import_task_id"] = task["task_id"]
                return data

            self.sessions.update(session_id, update_session)
            self._spawn(task["task_id"])
            project_type = str(project_config.get("project_type", "")).strip().lower()
            if project_type:
                public.set_module_logs("project_import", "import_project_{}".format(project_type))
            return public.return_message(0, 0, {
                "task_id": task["task_id"],
                "session_id": session_id,
            })
        except Exception as exc:
            return error_response(exc)

    def get_progress(self, get):
        try:
            return public.return_message(0, 0, self.tasks.public_progress(get.get("task_id", "")))
        except Exception as exc:
            return error_response(exc)

    def cancel_task(self, get):
        try:
            task_id = str(get.get("task_id", ""))
            task = self.tasks.request_cancel(task_id)
            pid = int(task.get("pid", 0) or 0)
            pgid = int(task.get("pgid", 0) or 0)
            if pid > 0:
                try:
                    if pgid > 0 and hasattr(os, "killpg"):
                        os.killpg(pgid, signal.SIGTERM)
                    else:
                        os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            return public.return_message(0, 0, {
                "task_id": task_id,
                "cancel_requested": True,
            })
        except Exception as exc:
            return error_response(exc)

    def _spawn(self, task_id):
        service_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "service.py")
        python_bin = public.get_python_bin()
        if not python_bin or not os.path.isfile(python_bin):
            raise ProjectImportError("Panel Python interpreter was not found", "PYTHON_NOT_FOUND")
        os.makedirs(logs_dir(), mode=0o700, exist_ok=True)
        log_path = os.path.join(logs_dir(), task_id + ".log")
        try:
            with open(log_path, "ab", buffering=0) as output:
                process = subprocess.Popen(
                    [python_bin, "-u", service_path, task_id],
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                    start_new_session=True,
                )
            self.tasks.set_process(task_id, process.pid, process.pid)
        except Exception as exc:
            self.tasks.set_failed(task_id, "Failed to start worker: {}".format(exc), "WORKER_START_FAILED")
            raise ProjectImportError("Failed to start import worker", "WORKER_START_FAILED")

    def _ensure_task_inactive(self, task_id):
        if not task_id:
            return
        try:
            task = self.tasks.get(task_id)
        except Exception:
            return
        if task.get("status") in (TASK_QUEUED, TASK_RUNNING):
            raise ProjectImportError("Another task in this stage is still running", "TASK_ALREADY_RUNNING")

    def _task_has_status(self, task_id, statuses):
        if not task_id:
            return False
        try:
            return self.tasks.get(task_id).get("status") in statuses
        except Exception:
            return False
