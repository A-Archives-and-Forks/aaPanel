# coding: utf-8

import sys

if "/www/server/panel" not in sys.path:
    sys.path.insert(0, "/www/server/panel")
if "/www/server/panel/class" not in sys.path:
    sys.path.insert(0, "/www/server/panel/class")
if "/www/server/panel/class_v2" not in sys.path:
    sys.path.insert(0, "/www/server/panel/class_v2")

import public

from mod.project.project_import.core.api_utils import error_response
from mod.project.project_import.core.constants import (
    PHP_RUNTIME_RECOMMENDED,
    PHP_RUNTIME_VERSIONS,
    TASK_QUEUED,
    TASK_RUNNING,
)
from mod.project.project_import.creators import (
    get_installed_nodejs_versions,
    get_installed_php_versions,
)
from mod.project.project_import.core.session_store import SessionStore
from mod.project.project_import.core.task_store import TaskStore


class main:
    def __init__(self):
        self.sessions = SessionStore()
        self.tasks = TaskStore()

    def create_session(self, get):
        try:
            source_type = str(get.get("source_type", "")).strip().lower()
            session = self.sessions.create(source_type)
            return public.return_message(0, 0, self.sessions.public_view(session["session_id"]))
        except Exception as exc:
            return error_response(exc)

    def get_session(self, get):
        try:
            return public.return_message(0, 0, self.sessions.public_view(get.get("session_id", "")))
        except Exception as exc:
            return error_response(exc)

    def cleanup_session(self, get):
        try:
            session = self.sessions.get(get.get("session_id", ""), allow_expired=True)
            for key in ("analysis_task_id", "import_task_id"):
                task_id = session.get(key, "")
                if not task_id:
                    continue
                try:
                    task = self.tasks.get(task_id)
                except Exception:
                    continue
                if task.get("status") in (TASK_QUEUED, TASK_RUNNING):
                    return public.return_message(-1, 0, "A task in this session is still running")
            self.sessions.cleanup(session["session_id"])
            return public.return_message(0, 0, "Import session cleaned")
        except Exception as exc:
            return error_response(exc)

    def get_capabilities(self, get=None):
        return public.return_message(0, 0, {
            # 运行时列表只含两种数据：用户已安装的版本 + 内置的默认版本，
            # 每项仅 label / value / installed 三个字段，前端下拉据此渲染；
            # 默认版本未安装时后端在 runtime 步骤自动安装
            "node_runtime_versions": get_installed_nodejs_versions()["options"],
            "php_runtime_versions": get_installed_php_versions(),
        })

    def get_nodejs_versions(self, get=None):
        """Return Node.js Manager runtimes currently installed on the server."""
        return public.return_message(0, 0, get_installed_nodejs_versions())

    def get_php_versions(self, get=None):
        """Return installable PHP runtimes supported by project import."""
        options = [
            {
                "label": "PHP {}.{}".format(version[0], version[1:]),
                "value": version,
                "recommended": version == PHP_RUNTIME_RECOMMENDED,
            }
            for version in PHP_RUNTIME_VERSIONS
        ]
        return public.return_message(0, 0, {
            "versions": list(PHP_RUNTIME_VERSIONS),
            "options": options,
            "recommended_version": PHP_RUNTIME_RECOMMENDED,
            "auto_install": True,
        })

    def check_database_name(self, get=None):
        """检查数据库名是否已存在（面板 databases 表 + 实际 MySQL 实例），供导入项目前前端防重名检查。

        参考 v2/data?action=getData&table=databases&search=xx，但直接按名字精确匹配，
        并额外核对实际 MySQL 实例（与 database_v2.AddDatabase 的重复检测口径一致）。
        """
        try:
            get = get or public.dict_obj()
            name = str(get.get("name", "")).strip().lower()
            dtype = str(get.get("dtype", "mysql")).strip().lower() or "mysql"
            if not name:
                return public.return_message(-1, 0, "Database name is required")
            panel_exists = public.M("databases").where(
                "LOWER(name)=? AND LOWER(type)=LOWER(?)", (name, dtype)
            ).count() > 0
            server_exists = None
            if dtype == "mysql":
                try:
                    mysql_obj = public.get_mysql_obj_by_sid(0)
                    db_list = mysql_obj.query("show databases")
                    try:
                        if not isinstance(db_list, list):
                            db_list = list(db_list)
                    except Exception:
                        db_list = []
                    db_names = [str(row[0]).lower() for row in db_list if row]
                    server_exists = name in db_names
                except Exception:
                    server_exists = None
            # return public.return_message(0, 0, {
            #     "name": name,
            #     "exists": bool(panel_exists) or bool(server_exists),
            #     # "panel_exists": bool(panel_exists),
            #     # "server_exists": server_exists,
            # })

            return public.return_message(0, 0, bool(panel_exists) or bool(server_exists))

        except Exception as exc:
            return error_response(exc)
