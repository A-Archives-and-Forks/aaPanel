# coding: utf-8

import gzip
import os
import shutil
import subprocess
import tempfile

from ..core.exceptions import ProjectImportError
from ..core.security import ensure_child_path
from .config_updater import update_database_config


class DatabaseImporter:
    def __init__(self, config, session, project_result, project_path, progress, cancelled):
        self.config = config or {}
        self.session = session
        self.project_result = project_result or {}
        self.project_path = project_path
        self.progress = progress
        self.cancelled = cancelled

    def run(self):
        if not self.config.get("enabled"):
            return {"enabled": False}
        import public
        from database_v2 import database as DatabaseModel

        name = str(self.config.get("database_name", "")).strip().lower()
        user = str(self.config.get("database_user", name)).strip().lower()
        password = str(self.config.get("database_password", ""))
        charset = str(self.config.get("charset", "utf8mb4"))
        if not name or not user or not password:
            raise ProjectImportError("Database name, user and password are required", "DATABASE_CONFIG_REQUIRED")
        # 在建库前先定位SQL文件 文件缺失直接失败
        sql_path = self._resolve_sql_file()
        args = public.to_dict_obj({
            "name": name,
            "db_user": user,
            "codeing": charset,
            "password": password,
            "sid": 0,
            "active": True,
            "address": "127.0.0.1",
            "ps": str(self.project_result.get("project_name", "Imported project")),
            "dtype": "MySQL",
            "pid": int(self.project_result.get("site_id", 0) or 0),
        })
        result = DatabaseModel().AddDatabase(args)
        status = result.get("status") if isinstance(result, dict) else None
        # 注意：success 时 status 为 0（return_message(0, ...)），不能写成
        # `status in (-1, False)`——Python 中 0 == False，会把成功误判为失败。
        if not isinstance(result, dict) or status is False or status == -1:
            message = result.get("message", result) if isinstance(result, dict) else result
            if isinstance(message, dict) and "result" in message:
                message = message["result"]
            raise ProjectImportError("Failed to create database: {}".format(message), "DATABASE_CREATE_FAILED")
        if sql_path:
            self._stream_sql(sql_path, name)
        database_id = public.M("databases").where("name=?", (name,)).getField("id") or 0
        updated = []
        if self.config.get("update_project_config"):
            updated = update_database_config(
                self.project_path,
                str(self.project_result.get("project_type", "")),
                {"name": name, "user": user, "password": password, "host": "127.0.0.1"},
            )
        return {
            "enabled": True,
            "database_id": int(database_id),
            "database_name": name,
            "database_user": user,
            "config_updated": [os.path.relpath(item, self.project_path).replace("\\", "/") for item in updated],
        }

    def _resolve_sql_file(self):
        """根据 sql_file_path 定位要导入的 SQL/SQL.GZ 文件。

        扫描到的文件（analysis.sql_files[].path）和用户上传到服务器指定目录的
        文件都以实际服务端路径传入；相对路径则相对项目根目录解析（限制在根目录内）。
        """
        configured = str(self.config.get("sql_file_path", "")).strip()
        if not configured:
            return ""
        if not os.path.isabs(configured):
            root = self.session.get("internal", {}).get("project_root", "")
            if not root:
                return ""
            configured = ensure_child_path(root, os.path.join(root, configured))
        path = os.path.realpath(configured)
        if os.path.isfile(path):
            return path
        raise ProjectImportError(
            "The selected SQL file does not exist on the server: {}".format(configured),
            "SQL_FILE_NOT_FOUND",
        )

    def _stream_sql(self, sql_path, database_name):
        import public
        mysql_bin = public.get_mysql_bin()
        if not mysql_bin or not os.path.isfile(mysql_bin):
            mysql_bin = shutil.which("mysql")
        if not mysql_bin:
            raise ProjectImportError("MySQL client was not found", "MYSQL_CLIENT_NOT_FOUND")
        root_password = public.M("config").where("id=?", (1,)).getField("mysql_root") or ""
        fd, defaults_file = tempfile.mkstemp(prefix="project_import_mysql_", suffix=".cnf")
        os.close(fd)
        try:
            with open(defaults_file, "w", encoding="utf-8") as handle:
                handle.write("[client]\nuser=root\npassword={}\ndefault-character-set=utf8mb4\n".format(root_password))
            os.chmod(defaults_file, 0o600)
            command = [mysql_bin, "--defaults-extra-file={}".format(defaults_file), database_name]
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            total = max(1, os.path.getsize(sql_path))
            source = gzip.open(sql_path, "rb") if sql_path.lower().endswith(".gz") else open(sql_path, "rb")
            try:
                while True:
                    self.cancelled()
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    process.stdin.write(chunk)
                    position = source.fileobj.tell() if hasattr(source, "fileobj") else source.tell()
                    self.progress(min(0.99, position / total), "Importing database")
                process.stdin.close()
                stderr = process.stderr.read().decode("utf-8", errors="ignore") if process.stderr else ""
                code = process.wait()
                if code != 0:
                    raise ProjectImportError("Database import failed: {}".format(stderr[-2000:]), "DATABASE_IMPORT_FAILED")
                self.progress(1, "Database import completed")
            finally:
                source.close()
                if process.poll() is None:
                    process.terminate()
        finally:
            try:
                os.remove(defaults_file)
            except OSError:
                pass

