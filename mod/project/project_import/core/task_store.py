# coding: utf-8

import os
import time

from .constants import (
    STEP_FAILED,
    STEP_RUNNING,
    STEP_SUCCESS,
    STEP_WAITING,
    TASK_CANCELLED,
    TASK_FAILED,
    TASK_ID_RE,
    TASK_QUEUED,
    TASK_RUNNING,
    TASK_SUCCESS,
    locks_dir,
    new_id,
    secrets_dir,
    tasks_dir,
)
from .exceptions import ProjectImportError
from .json_store import atomic_write_json, file_lock, read_json


class TaskStore:
    def _validate_id(self, task_id):
        if not TASK_ID_RE.match(str(task_id or "")):
            raise ProjectImportError("Invalid task ID", "INVALID_TASK_ID")
        return str(task_id)

    def _path(self, task_id):
        return os.path.join(tasks_dir(), self._validate_id(task_id) + ".json")

    def _lock_path(self, task_id):
        return os.path.join(locks_dir(), self._validate_id(task_id) + ".lock")

    def _secret_path(self, task_id):
        return os.path.join(secrets_dir(), self._validate_id(task_id) + ".json")

    def create(self, task_type, session_id, steps, payload=None, secret=None):
        prefix = "pia" if task_type == "analysis" else "pii"
        task_id = new_id(prefix)
        now = int(time.time())
        record = {
            "task_id": task_id,
            "session_id": session_id,
            "task_type": task_type,
            "status": TASK_QUEUED,
            "progress": 0,
            "stage": "queued",
            "steps": [self._normalize_step(item) for item in steps],
            "result": {},
            "warnings": [],
            "error": "",
            "error_code": "",
            "cancel_requested": False,
            "pid": 0,
            "pgid": 0,
            "payload": payload or {},
            "created_at": now,
            "started_at": 0,
            "updated_at": now,
            "finished_at": 0,
            "heartbeat_at": now,
        }
        atomic_write_json(self._path(task_id), record)
        if secret:
            atomic_write_json(self._secret_path(task_id), secret)
        return record

    @staticmethod
    def _normalize_step(step):
        data = dict(step)
        return {
            "key": str(data.get("key", "")),
            "title": str(data.get("title", "")),
            "status": int(data.get("status", STEP_WAITING)),
            "progress": int(data.get("progress", 0)),
            "ps": str(data.get("ps", "")),
            "error": str(data.get("error", "")),
        }

    def get(self, task_id):
        data = read_json(self._path(task_id))
        if not isinstance(data, dict):
            raise ProjectImportError("Task does not exist", "TASK_NOT_FOUND")
        return data

    def update(self, task_id, updater):
        with file_lock(self._lock_path(task_id)):
            data = self.get(task_id)
            result = updater(data)
            if isinstance(result, dict):
                data = result
            data["updated_at"] = int(time.time())
            atomic_write_json(self._path(task_id), data)
            return data

    def get_secret(self, task_id, default=None):
        return read_json(self._secret_path(task_id), default=default)

    def delete_secret(self, task_id):
        path = self._secret_path(task_id)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def set_process(self, task_id, pid, pgid=0):
        def apply(data):
            data["pid"] = int(pid or 0)
            data["pgid"] = int(pgid or 0)
            return data
        return self.update(task_id, apply)

    def set_running(self, task_id):
        now = int(time.time())
        def apply(data):
            data["status"] = TASK_RUNNING
            data["stage"] = "starting"
            data["started_at"] = data.get("started_at") or now
            data["heartbeat_at"] = now
            return data
        return self.update(task_id, apply)

    def heartbeat(self, task_id, message=None):
        now = int(time.time())
        def apply(data):
            data["heartbeat_at"] = now
            if message is not None:
                data["message"] = str(message)
            return data
        return self.update(task_id, apply)

    def update_step(self, task_id, key, status=None, ps=None, error=None,
                    progress=None, stage=None, total_progress=None):
        def apply(data):
            found = False
            for step in data.get("steps", []):
                if step.get("key") != key:
                    continue
                found = True
                if status is not None:
                    step["status"] = int(status)
                if ps is not None:
                    step["ps"] = str(ps)
                if error is not None:
                    step["error"] = str(error)
                if progress is not None:
                    step["progress"] = max(0, min(100, int(progress)))
                break
            if not found:
                raise ProjectImportError("Unknown task step: {}".format(key), "UNKNOWN_TASK_STEP")
            if stage is not None:
                data["stage"] = str(stage)
            if total_progress is not None:
                data["progress"] = max(int(data.get("progress", 0)), min(99, int(total_progress)))
            data["heartbeat_at"] = int(time.time())
            return data
        return self.update(task_id, apply)

    def add_warning(self, task_id, warning):
        def apply(data):
            text = str(warning)
            if text and text not in data.setdefault("warnings", []):
                data["warnings"].append(text)
            return data
        return self.update(task_id, apply)

    def set_success(self, task_id, result=None):
        now = int(time.time())
        def apply(data):
            data["status"] = TASK_SUCCESS
            data["progress"] = 100
            data["stage"] = "finished"
            data["result"] = result or {}
            data["finished_at"] = now
            data["heartbeat_at"] = now
            for step in data.get("steps", []):
                if step.get("status") in (STEP_WAITING, STEP_RUNNING):
                    step["status"] = STEP_SUCCESS
                    step["progress"] = 100
            return data
        return self.update(task_id, apply)

    def set_failed(self, task_id, message, error_code="PROJECT_IMPORT_ERROR"):
        now = int(time.time())
        def apply(data):
            data["status"] = TASK_FAILED
            data["stage"] = "failed"
            data["error"] = str(message)
            data["error_code"] = str(error_code)
            data["finished_at"] = now
            data["heartbeat_at"] = now
            for step in data.get("steps", []):
                if step.get("status") == STEP_RUNNING:
                    step["status"] = STEP_FAILED
                    step["error"] = str(message)
                    break
            return data
        return self.update(task_id, apply)

    def set_cancelled(self, task_id, message="Task cancelled"):
        now = int(time.time())
        def apply(data):
            data["status"] = TASK_CANCELLED
            data["stage"] = "cancelled"
            data["error"] = str(message)
            data["error_code"] = "TASK_CANCELLED"
            data["finished_at"] = now
            data["heartbeat_at"] = now
            for step in data.get("steps", []):
                if step.get("status") == STEP_RUNNING:
                    step["status"] = STEP_FAILED
                    step["error"] = str(message)
                    break
            return data
        return self.update(task_id, apply)

    def request_cancel(self, task_id):
        def apply(data):
            if data.get("status") in (TASK_SUCCESS, TASK_FAILED, TASK_CANCELLED):
                return data
            data["cancel_requested"] = True
            return data
        return self.update(task_id, apply)

    def is_cancel_requested(self, task_id):
        return bool(self.get(task_id).get("cancel_requested"))

    def public_progress(self, task_id):
        data = self.get(task_id)
        return {
            "task_id": data["task_id"],
            "session_id": data.get("session_id", ""),
            "task_type": data.get("task_type", ""),
            "status": int(data.get("status", TASK_QUEUED)),
            "progress": int(data.get("progress", 0)),
            "stage": data.get("stage", ""),
            "steps": data.get("steps", []),
            "result": data.get("result", {}),
            "warnings": data.get("warnings", []),
            "error": data.get("error", ""),
            "error_code": data.get("error_code", ""),
            "can_cancel": data.get("status") in (TASK_QUEUED, TASK_RUNNING),
            "created_at": data.get("created_at", 0),
            "started_at": data.get("started_at", 0),
            "updated_at": data.get("updated_at", 0),
            "finished_at": data.get("finished_at", 0),
            "heartbeat_at": data.get("heartbeat_at", 0),
        }

