# coding: utf-8

import os
import shutil
import time

from .constants import (
    DEFAULT_SESSION_TTL,
    SESSION_ID_RE,
    locks_dir,
    new_id,
    sessions_dir,
    upload_root,
    work_root,
)
from .exceptions import ProjectImportError
from .json_store import atomic_write_json, file_lock, read_json


class SessionStore:
    SUPPORTED_SOURCES = ("archive", "local", "git", "ftp", "sftp", "ssh")

    def _validate_id(self, session_id):
        if not SESSION_ID_RE.match(str(session_id or "")):
            raise ProjectImportError("Invalid session ID", "INVALID_SESSION_ID")
        return str(session_id)

    def _path(self, session_id):
        return os.path.join(sessions_dir(), self._validate_id(session_id) + ".json")

    def _lock_path(self, session_id):
        return os.path.join(locks_dir(), self._validate_id(session_id) + ".session.lock")

    def work_dir(self, session_id):
        return os.path.join(work_root(), self._validate_id(session_id))

    def create(self, source_type):
        source_type = str(source_type or "").lower().strip()
        if source_type not in self.SUPPORTED_SOURCES:
            raise ProjectImportError("Unsupported source type", "UNSUPPORTED_SOURCE")
        session_id = new_id("pis")
        now = int(time.time())
        # todo 多余返回参数用途?
        record = {
            "session_id": session_id,
            "source_type": source_type,
            "status": "created",
            "analysis_task_id": "",
            "import_task_id": "",
            "upload": {},
            "source": {},
            "analysis": {},
            "internal": {},
            "created_at": now,
            "updated_at": now,
            "expires_at": now + DEFAULT_SESSION_TTL,
        }
        os.makedirs(self.work_dir(session_id), mode=0o700, exist_ok=True)
        atomic_write_json(self._path(session_id), record)
        return record

    def get(self, session_id, allow_expired=False):
        data = read_json(self._path(session_id))
        if not isinstance(data, dict):
            raise ProjectImportError("Import session does not exist", "SESSION_NOT_FOUND")
        if not allow_expired and int(data.get("expires_at", 0)) < int(time.time()):
            raise ProjectImportError("Import session has expired", "SESSION_EXPIRED")
        return data

    def update(self, session_id, updater):
        with file_lock(self._lock_path(session_id)):
            data = self.get(session_id, allow_expired=True)
            result = updater(data)
            if isinstance(result, dict):
                data = result
            data["updated_at"] = int(time.time())
            atomic_write_json(self._path(session_id), data)
            return data

    def public_view(self, session_id):
        data = self.get(session_id)
        return {
            "session_id": data["session_id"],
            "source_type": data.get("source_type", ""),
            "status": data.get("status", ""),
            "analysis_task_id": data.get("analysis_task_id", ""),
            "import_task_id": data.get("import_task_id", ""),
            "upload": self._public_upload(data.get("upload", {})),
            "source": data.get("source", {}),
            "analysis": data.get("analysis", {}),
            "created_at": data.get("created_at", 0),
            "updated_at": data.get("updated_at", 0),
            "expires_at": data.get("expires_at", 0),
        }

    @staticmethod
    def _public_upload(upload):
        if not isinstance(upload, dict):
            return {}
        return {
            key: upload.get(key)
            for key in ("upload_id", "file_name", "file_size", "uploaded_size", "completed")
            if key in upload
        }

    def cleanup_work_dir(self, session_id):
        """删除会话的临时工作区（/www/backup/project_import/<session_id>），保留会话 JSON。

        导入成功后项目文件已提交到目标站点，work_dir 里的下载副本、分片上传临时文件都不再需要，及时释放
        """
        session_id = self._validate_id(session_id)
        work_path = os.path.realpath(self.work_dir(session_id))
        root_path = os.path.realpath(work_root())
        try:
            valid = os.path.commonpath([work_path, root_path]) == root_path and work_path != root_path
        except ValueError:
            valid = False
        if not valid:
            return False
        if os.path.isdir(work_path):
            shutil.rmtree(work_path, ignore_errors=True)
        return True

    def cleanup(self, session_id):
        session_id = self._validate_id(session_id)
        session_path = self._path(session_id)
        work_path = os.path.realpath(self.work_dir(session_id))
        root_path = os.path.realpath(work_root())
        if os.path.commonpath([work_path, root_path]) != root_path or work_path == root_path:
            raise ProjectImportError("Unsafe cleanup path", "UNSAFE_CLEANUP_PATH")
        if os.path.isdir(work_path):
            shutil.rmtree(work_path, ignore_errors=True)
        if os.path.exists(session_path):
            os.remove(session_path)

    @staticmethod
    def cleanup_upload_root(max_age=None):
        """兜底清理上传区中的孤儿压缩包。

        ``upload_root()``（/www/backup/project_import_upload）是前后端约定的
        压缩包上传目录，文件在分析阶段被解压消费；消费后由 executor 在分析
        成功时删除。这里清理两类残留：上传后从未分析、或分析失败后用户不再
        处理的过期文件。只删该目录下的普通文件，不动子目录，避免误删。
        """
        root = os.path.realpath(upload_root())
        if not os.path.isdir(root):
            return 0
        max_age = int(max_age if max_age is not None else DEFAULT_SESSION_TTL)
        now = int(time.time())
        removed = 0
        for name in os.listdir(root):
            path = os.path.join(root, name)
            try:
                if not os.path.isfile(path):
                    continue
                if now - int(os.path.getmtime(path)) >= max_age:
                    os.remove(path)
                    removed += 1
            except OSError:
                continue
        return removed

