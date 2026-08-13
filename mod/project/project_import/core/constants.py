# coding: utf-8

import os
import re
import time
import uuid


SESSION_ID_RE = re.compile(r"^pis_[0-9]{8}_[0-9a-f]{12}$")
TASK_ID_RE = re.compile(r"^pi[ai]_[0-9]{8}_[0-9a-f]{12}$")
TASK_QUEUED = 2
TASK_RUNNING = 0
TASK_SUCCESS = 1
TASK_FAILED = -1
TASK_CANCELLED = -2

STEP_WAITING = 2
STEP_RUNNING = 0
STEP_SUCCESS = 1
STEP_FAILED = -1

DEFAULT_SESSION_TTL = 24 * 3600
MAX_UPLOAD_SIZE = 5 * 1024 * 1024 * 1024
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
PHP_RUNTIME_VERSIONS = ('84', '83', '82')
PHP_RUNTIME_RECOMMENDED = '83'
NODE_RUNTIME_VERSIONS = ("v26.1.0", "v24.15.0", "v22.22.3")
NODE_RUNTIME_RECOMMENDED = "v24.15.0"



def _panel_path():
    try:
        import public
        return public.get_panel_path()
    except Exception:
        return os.environ.get("AAPANEL_PANEL_PATH", "/www/server/panel")


def data_root():
    return os.environ.get(
        "AAPANEL_PROJECT_IMPORT_DATA",
        os.path.join(_panel_path(), "data", "project_import"),
    )


def work_root():
    return os.environ.get(
        "AAPANEL_PROJECT_IMPORT_WORK",
        "/www/backup/project_import",
    )


def upload_root():
    """前后端约定的压缩包上传目录。
    清理逻辑删除（见 executor / session_store.cleanup_upload_root）。
    """
    return os.environ.get(
        "AAPANEL_PROJECT_IMPORT_UPLOAD",
        "/www/backup/project_import_upload",
    )


def tasks_dir():
    return os.path.join(data_root(), "tasks")


def sessions_dir():
    return os.path.join(data_root(), "sessions")


def secrets_dir():
    return os.path.join(data_root(), "secrets")


def locks_dir():
    return os.path.join(data_root(), "locks")


def logs_dir():
    return os.path.join(data_root(), "logs")


def new_id(prefix):
    return "{}_{}_{}".format(prefix, time.strftime("%Y%m%d"), uuid.uuid4().hex[:12])


def ensure_runtime_dirs():
    for path in (data_root(), tasks_dir(), sessions_dir(), secrets_dir(), locks_dir(), logs_dir(), work_root()):
        os.makedirs(path, mode=0o700, exist_ok=True)
