# coding: utf-8

import os
import sys

if "/www/server/panel" not in sys.path:
    sys.path.insert(0, "/www/server/panel")
if "/www/server/panel/class" not in sys.path:
    sys.path.insert(0, "/www/server/panel/class")

import public

from mod.project.project_import.core.api_utils import error_response
from mod.project.project_import.core.constants import MAX_UPLOAD_SIZE, locks_dir, new_id
from mod.project.project_import.core.exceptions import ProjectImportError
from mod.project.project_import.core.json_store import file_lock
from mod.project.project_import.core.security import ensure_child_path
from mod.project.project_import.core.session_store import SessionStore


ALLOWED_ARCHIVES = (".zip", ".tar", ".tar.gz", ".tgz")


class main:
    def __init__(self):
        self.sessions = SessionStore()

    def upload(self, get):
        """Wrap files.upload with a session-scoped fixed destination."""
        try:
            from BTPanel import request
            from files import files as PanelFiles

            file_name = os.path.basename(str(get.get("f_name", "")).strip())
            file_size = int(get.get("f_size", 0) or 0)
            offset = int(get.get("f_start", 0) or 0)
            if not file_name or not file_name.lower().endswith(ALLOWED_ARCHIVES):
                raise ProjectImportError("Unsupported archive format", "UNSUPPORTED_ARCHIVE")
            if file_size <= 0 or file_size > MAX_UPLOAD_SIZE:
                raise ProjectImportError("Invalid upload file size", "UPLOAD_SIZE_INVALID")
            if offset < 0 or offset > file_size:
                raise ProjectImportError("Invalid upload offset", "UPLOAD_OFFSET_INVALID")
            if not request.files.getlist("blob"):
                raise ProjectImportError("Upload chunk is missing", "UPLOAD_CHUNK_REQUIRED")

            session_id = str(get.get("session_id", "")).strip()
            if session_id:
                session = self.sessions.get(session_id)
                if session.get("source_type") != "archive":
                    raise ProjectImportError("This session is not an archive session", "INVALID_SOURCE_TYPE")
            else:
                if offset != 0:
                    raise ProjectImportError(
                        "session_id is required after the first upload chunk",
                        "UPLOAD_SESSION_REQUIRED",
                    )
                session = self.sessions.create("archive")
                session_id = session["session_id"]

            upload_dir = os.path.join(self.sessions.work_dir(session_id), "upload")
            os.makedirs(upload_dir, mode=0o700, exist_ok=True)
            temporary_path = ensure_child_path(
                upload_dir,
                os.path.join(upload_dir, file_name + "." + str(file_size) + ".upload.tmp"),
            )
            final_path = ensure_child_path(upload_dir, os.path.join(upload_dir, file_name))
            lock_path = os.path.join(locks_dir(), session_id + ".upload.lock")

            with file_lock(lock_path):
                session = self.sessions.get(session_id)
                upload = session.get("upload", {})
                same_file = (
                    upload.get("file_name") == file_name
                    and int(upload.get("file_size", 0) or 0) == file_size
                )
                if (
                    same_file
                    and upload.get("completed")
                    and os.path.isfile(final_path)
                    and os.path.getsize(final_path) == file_size
                    and offset == file_size
                ):
                    return public.return_message(0, 0, self._result(session_id, upload))

                if not same_file or upload.get("completed"):
                    if offset != 0:
                        expected = file_size if same_file and upload.get("completed") else 0
                        raise ProjectImportError(
                            "Unexpected upload offset; expected {}".format(expected),
                            "UPLOAD_OFFSET_MISMATCH",
                        )
                    self._remove_previous_upload(upload_dir, upload)
                    upload = {
                        "upload_id": new_id("piu"),
                        "file_name": file_name,
                        "file_size": file_size,
                        "uploaded_size": 0,
                        "completed": False,
                        "part_path": temporary_path,
                        "path": final_path,
                    }

                    def initialize(data):
                        data["upload"] = dict(upload)
                        data["status"] = "uploading"
                        return data

                    self.sessions.update(session_id, initialize)

                current_size = os.path.getsize(temporary_path) if os.path.isfile(temporary_path) else 0
                if current_size != offset:
                    raise ProjectImportError(
                        "Unexpected upload offset; expected {}".format(current_size),
                        "UPLOAD_OFFSET_MISMATCH",
                    )

                args = public.to_dict_obj({
                    "f_path": upload_dir,
                    "f_name": file_name,
                    "f_size": file_size,
                    "f_start": offset,
                })
                try:
                    upstream = PanelFiles().upload(args)
                except Exception:
                    self._rollback_partial(temporary_path, current_size)
                    raise

                completed = os.path.isfile(final_path) and os.path.getsize(final_path) == file_size
                if completed:
                    uploaded_size = file_size
                else:
                    uploaded_size = os.path.getsize(temporary_path) if os.path.isfile(temporary_path) else 0
                    if uploaded_size > file_size:
                        self._rollback_partial(temporary_path, current_size)
                        raise ProjectImportError(
                            "Uploaded data exceeds declared size",
                            "UPLOAD_SIZE_EXCEEDED",
                        )
                    if type(upstream) is not int:
                        self._rollback_partial(temporary_path, current_size)
                        raise ProjectImportError(
                            self._upstream_error(upstream),
                            "FILE_UPLOAD_FAILED",
                        )

                def save_progress(data):
                    data["upload"] = dict(upload)
                    data["upload"]["uploaded_size"] = uploaded_size
                    data["upload"]["completed"] = completed
                    if completed:
                        data["upload"].pop("part_path", None)
                        data["status"] = "created"
                    else:
                        data["status"] = "uploading"
                    return data

                saved = self.sessions.update(session_id, save_progress)
                return public.return_message(0, 0, self._result(session_id, saved["upload"]))
        except Exception as exc:
            return error_response(exc)

    @staticmethod
    def _result(session_id, upload):
        uploaded_size = int(upload.get("uploaded_size", 0) or 0)
        return {
            "session_id": session_id,
            "upload_id": upload.get("upload_id", ""),
            "file_name": upload.get("file_name", ""),
            "file_size": int(upload.get("file_size", 0) or 0),
            "uploaded_size": uploaded_size,
            "next_start": uploaded_size,
            "completed": bool(upload.get("completed")),
        }

    @staticmethod
    def _rollback_partial(path, size):
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r+b") as handle:
                handle.truncate(max(0, int(size)))
        except OSError:
            pass

    @staticmethod
    def _upstream_error(result):
        if isinstance(result, dict):
            message = result.get("message", result.get("msg", result.get("result", "")))
            if isinstance(message, dict):
                message = message.get("result", message.get("error", ""))
            if message:
                return str(message)
        return "File upload failed"

    @staticmethod
    def _remove_previous_upload(upload_dir, upload):
        for field in ("part_path", "path"):
            path = str(upload.get(field, ""))
            if not path:
                continue
            try:
                path = ensure_child_path(upload_dir, path)
            except ProjectImportError:
                continue
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
