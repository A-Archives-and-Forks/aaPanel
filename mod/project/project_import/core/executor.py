# coding: utf-8

import os
import shutil
import socket
import time

from .cleanup import remove_created_destination
from .constants import STEP_SUCCESS, upload_root
from .detector import ProjectDetector
from .exceptions import ProjectImportError
from .progress import ProgressReporter
from .resource_ledger import ResourceLedger
from .security import safe_realpath
from .session_store import SessionStore
from .task_store import TaskStore
from ..creators import (
    get_creator,
    prepare_node_config,
    prepare_node_runtime,
    prepare_php_config,
    prepare_php_runtime,
)
from ..database import DatabaseImporter
from ..sources import get_source_adapter
from ..sources.base import copy_directory
from ..sources.git import bind_site_git, normalize_git_config
from git_auth import encrypt_git_token


ANALYSIS_WEIGHTS = {
    "validate_source": 5,
    "fetch_source": 65,
    "detect_project": 25,
    "finalize": 5,
}

IMPORT_WEIGHTS = {
    "preflight": 8,
    "runtime": 20,
    "commit_files": 17,
    "create_project": 22,
    "database": 20,
    "ssl": 7,
    "health": 6,
}


def execute_task(task_id):
    store = TaskStore()
    task = store.get(task_id)
    if task.get("task_type") == "analysis":
        return execute_analysis(task_id)
    if task.get("task_type") == "import":
        return execute_import(task_id)
    raise ProjectImportError("Unknown task type", "UNKNOWN_TASK_TYPE")


def execute_analysis(task_id):
    store = TaskStore()
    sessions = SessionStore()
    task = store.get(task_id)
    session_id = task.get("session_id", "")
    session = sessions.get(session_id)
    secret = store.get_secret(task_id, default={}) or {}
    source_config = secret.get("source_config", {})
    reporter = ProgressReporter(store, task_id, ANALYSIS_WEIGHTS)

    reporter.start("validate_source", "Validating project source")
    source_type = str(session.get("source_type", "")).lower()
    if not source_type:
        raise ProjectImportError("Source type is missing", "SOURCE_TYPE_REQUIRED")
    work_dir = sessions.work_dir(session_id)
    os.makedirs(work_dir, mode=0o700, exist_ok=True)
    reporter.finish("validate_source", "Source validation completed")

    reporter.start("fetch_source", "Preparing project files")
    adapter = get_source_adapter(
        source_type,
        session=session,
        config=source_config,
        work_dir=work_dir,
        reporter=reporter,
    )
    source_result = adapter.fetch()
    project_root = safe_realpath(source_result["path"])
    reporter.finish("fetch_source", "Project files are ready")

    reporter.start("detect_project", "Analyzing project files")
    detector = ProjectDetector(project_root)
    # detector = ProjectDetector(
    #     project_root,
    #     name_hint=source_result.get("name", ""),
    # )
    analysis = detector.scan(
        progress=lambda ratio, message: reporter.update("detect_project", ratio, message),
        cancelled=reporter.check_cancelled,
    )
    reporter.finish("detect_project", "Project analysis completed")

    reporter.start("finalize", "Saving analysis result")
    public_source = {
        "mode": source_result.get("mode", "staged"),
        "summary": source_result.get("summary", ""),
    }

    def save_result(data):
        data["status"] = "analyzed"
        data["source"] = public_source
        data["analysis"] = analysis
        data.setdefault("internal", {})["project_root"] = project_root
        data["internal"]["source_mode"] = source_result.get("mode", "staged")
        git_bind = _git_bind_from_source(source_type, source_config)
        if git_bind:
            data["internal"]["git_bind"] = git_bind
        return data

    sessions.update(session_id, save_result)
    reporter.finish("finalize", "Analysis result saved")
    result = dict(analysis)
    result["session_id"] = session_id
    result["source"] = public_source
    store.set_success(task_id, result)
    store.delete_secret(task_id)
    _cleanup_consumed_upload(source_type, source_config)
    return result


def execute_import(task_id):
    store = TaskStore()
    sessions = SessionStore()
    task = store.get(task_id)
    session_id = task.get("session_id", "")
    session = sessions.get(session_id)
    secret = store.get_secret(task_id, default={}) or {}
    project_config = secret.get("project_config", {})
    database_config = secret.get("database_config", {})
    reporter = ProgressReporter(store, task_id, IMPORT_WEIGHTS)
    work_dir = sessions.work_dir(session_id)
    ledger = ResourceLedger(os.path.join(work_dir, "resource_ledger_{}.json".format(task_id)))
    destination_created = False
    project_result = {}

    try:
        reporter.start("preflight", "Validating import settings")
        source_root, source_mode, destination, project_type = _preflight(session, project_config)
        reporter.finish("preflight", "Import settings validated")

        reporter.start("runtime", "Preparing project runtime")
        # 1. 公共基础设施：Web 服务器（Nginx）与数据库（MySQL），参考引导页逻辑检查/安装
        _prepare_infrastructure(
            database_config,
            progress=lambda ratio, message: reporter.update("runtime", ratio * 0.5, message),
            cancelled=reporter.check_cancelled,
        )
        # 2. 项目运行时
        if project_type == "node":
            prepare_node_runtime(
                project_config,
                progress=lambda ratio, message: reporter.update("runtime", 0.5 + ratio * 0.5, message),
            )
            reporter.finish("runtime", "Node.js runtime is ready")
        elif project_type == "php":
            prepare_php_runtime(
                project_config,
                progress=lambda ratio, message: reporter.update("runtime", 0.5 + ratio * 0.5, message),
            )
            reporter.finish("runtime", "PHP runtime is ready")
        else:
            reporter.finish("runtime", "Runtime preparation was not requested")
        reporter.start("commit_files", "Preparing destination directory")
        if source_mode == "register":
            project_path = source_root
            reporter.update("commit_files", 1, "Using the existing local directory", force=True)
        else:
            project_path = _commit_files(
                source_root,
                destination,
                task_id,
                progress=lambda ratio, message: reporter.update("commit_files", ratio, message),
                cancelled=reporter.check_cancelled,
            )
            destination_created = True
            ledger.record("destination_created", True)
            ledger.record("destination", project_path)
        reporter.finish("commit_files", "Project files committed")

        reporter.start("create_project", "Creating aaPanel project")
        creator = get_creator(project_type, config=project_config, project_path=project_path)
        project_result = creator.create()
        ledger.record("site_id", int(project_result.get("site_id", 0) or 0))
        for warning in project_result.get("warnings", []):
            store.add_warning(task_id, warning)
        create_message = "aaPanel project created"
        if project_result.get("warnings"):
            create_message = "aaPanel project created with startup warnings"
        reporter.finish("create_project", create_message)

        git_bind = session.get("internal", {}).get("git_bind")
        site_id = int(project_result.get("site_id", 0) or 0)
        if git_bind and site_id:
            bind_result = bind_site_git(site_id, project_path, git_bind)
            if bind_result.get("warning"):
                store.add_warning(task_id, bind_result["warning"])
            if bind_result.get("bound"):
                def clear_git_bind(data):
                    data.setdefault("internal", {}).pop("git_bind", None)
                    return data
                sessions.update(session_id, clear_git_bind)

        reporter.start("database", "Preparing database")
        database_result = {"enabled": False}
        if database_config.get("enabled"):
            try:
                database_result = DatabaseImporter(
                    database_config,
                    session,
                    project_result,
                    project_path,
                    progress=lambda ratio, message: reporter.update("database", ratio, message),
                    cancelled=reporter.check_cancelled,
                ).run()
                if database_result.get("database_id"):
                    ledger.record("database_id", database_result["database_id"])
                reporter.finish("database", "Database import completed")
            except ProjectImportError as exc:
                warning = "Database step failed: {}".format(exc)
                store.add_warning(task_id, warning)
                store.update_step(
                    task_id, "database", status=STEP_SUCCESS, progress=100,
                    ps=warning, error="", stage="database", total_progress=93,
                )
                database_result = {"enabled": True, "status": "warning", "message": str(exc)}
        else:
            reporter.finish("database", "Database import was not requested")

        reporter.start("ssl", "Checking SSL configuration")
        ssl_result = _ssl_result(project_type, project_config, project_result)
        if ssl_result.get("warning"):
            store.add_warning(task_id, ssl_result["warning"])
        reporter.finish("ssl", ssl_result.get("message", "SSL step completed"))

        reporter.start("health", "Checking imported project")
        health = _health_check(project_result, project_path)
        if health.get("warning"):
            store.add_warning(task_id, health["warning"])
        reporter.finish("health", health.get("message", "Health check completed"))

        result = dict(project_result)
        result.update({
            "session_id": session_id,
            "database": database_result,
            "ssl": ssl_result,
            "health": health,
            "warnings": store.get(task_id).get("warnings", []),
        })

        def save_import(data):
            data["status"] = "imported"
            data["import_result"] = result
            return data

        sessions.update(session_id, save_import)
        store.set_success(task_id, result)
        # 导入成功后清理会话临时工作区（/www/backup/project_import/<session_id>）：
        sessions.cleanup_work_dir(session_id)

        return result
    except Exception:
        site_id = int(project_result.get("site_id", 0) or 0)
        if not site_id and destination_created:
            site_id = _panel_site_id("path", ledger.get("destination", ""))
            if site_id:
                ledger.record("site_id", site_id)
        if destination_created and not site_id:
            try:
                remove_created_destination(ledger.get("destination", ""))
            except Exception:
                pass
        raise
    finally:
        store.delete_secret(task_id)
        # # 导入成功或失败都清理会话临时工作区（/www/backup/project_import/<session_id>），
        # sessions.cleanup_work_dir(session_id)


def _cleanup_consumed_upload(source_type, source_config):
    """删除分析阶段已消费的临时上传压缩包。
    """
    if str(source_type).lower() not in ("local", "archive"):
        return
    candidate = str(source_config.get("path", "")).strip()
    if not candidate:
        return
    try:
        root = os.path.realpath(upload_root())
        path = os.path.realpath(candidate)
        if os.path.commonpath([root, path]) == root and os.path.isfile(path):
            os.remove(path)
    except (ValueError, OSError):
        pass


def _git_bind_from_source(source_type, source_config):
    """ssh_key 认证的 git 源 → git 管理器绑定信息；public/token 暂不兼容返回 None。"""
    if str(source_type).lower() != "git":
        return None
    try:
        normalized = normalize_git_config(source_config)
    except ProjectImportError:
        return None
    auth_type = normalized.get("auth_type")
    result = {
        "repo": normalized["repository"],
        "branch": normalized.get("branch", ""),
        "auth_type": "ssh" if auth_type == "ssh_key" else auth_type,
    }
    if auth_type == "ssh_key":
        result["key_path"] = normalized["key_path"]
    elif auth_type == "token":
        result["username"] = normalized["username"]
        result["token_encrypted"] = encrypt_git_token(normalized["token"])
    return result


DEPENDENCY_INSTALL_TIMEOUT = 900


def _clean_stale_dependency_tasks(name):
    """清理指定软件残留的安装任务，让 add_soft_install_task 能重新排队。

    add_soft_install_task 仅在任务表里没有该软件的活动任务时才排队安装，
    因此失败的残留任务（status!=1）会一直阻塞后续安装，直到 _wait_dependency_install
    轮询超时。清理前先确认该软件的 install_soft.sh 进程已不在运行，避免误删
    正在进行的安装；确认无残留安装进程后才删除任务并触发面板任务队列。
    返回 True 表示已清理或无需清理，False 表示安装仍在进行。
    """
    try:
        import subprocess
        output = subprocess.check_output(
            ["ps", "-ef"],
            stderr=subprocess.STDOUT,
        ).decode("utf-8", "replace")
        active = any(
            "install_soft.sh" in line
            and name in line
            and "panelExec" not in line
            for line in output.splitlines()
        )
        if active:
            return False
    except Exception:
        pass

    try:
        import public
        tasks = public.M("tasks").where(
            "status!=? and name LIKE ?", ("1", "%" + name + "%")
        ).field("id").select()
        if not isinstance(tasks, list) or not tasks:
            return True
        for task in tasks:
            public.M("tasks").delete(task.get("id"))
        public.writeFile("/tmp/panelTask.pl", "True")
        return True
    except Exception:
        return False


def _prepare_infrastructure(database_config, progress, cancelled):
    """确保公共基础设施就绪：Web 服务器（Nginx）与数据库（MySQL）。

    参考引导页 panel_guide_page.install_plugin 的检查/安装机制：
    get_plugin_status 判断是否已装，add_soft_install_task 排队异步安装，
    轮询面板 tasks 表等待安装完成。仅在缺失时安装，已装则跳过。
    安装失败/超时抛出 ProjectImportError，导入在 runtime 步骤中断。
    """
    import public
    from panel_guide_page import GuidePage

    guide = GuidePage()
    installs = []

    # Web 服务器：php/static/node 建站都依赖；面板已用 Apache/OpenLiteSpeed 时视为就绪
    webserver = public.get_webserver()
    if webserver not in ("apache", "openlitespeed") and not guide.get_plugin_status("nginx", "1.30"):
        installs.append(("nginx", "1.30", "Nginx"))

    # 数据库：仅启用数据库导入步骤时需要（当前导入仅支持 MySQL）
    if bool(database_config.get("enabled")) and not guide.get_plugin_status("mysql", "8.0"):
        installs.append(("mysql", "8.0", "MySQL"))

    total = max(1, len(installs))
    for index, (name, version, display) in enumerate(installs):
        cancelled()
        slot_start = index / total
        slot_end = (index + 1) / total
        if progress:
            progress(slot_start + 0.02, "Installing {}".format(display))
        # 残留的失败任务会阻塞 add_soft_install_task 排队，先清理（确认安装进程已死）
        _clean_stale_dependency_tasks(name)
        if not guide.add_soft_install_task(name, version):
            raise ProjectImportError(
                "Failed to queue {} installation".format(display),
                "DEPENDENCY_QUEUE_FAILED",
            )
        _wait_dependency_install(guide, name, version, display, progress, cancelled, slot_start, slot_end)
    return True


def _wait_dependency_install(guide, name, version, display, progress, cancelled, slot_start, slot_end):
    """轮询等待 add_soft_install_task 排队的面板安装任务完成。

    任务表里没有该软件的活动安装任务（未排队或已结束）时停止等待；
    最后再确认一次安装状态，仍未就绪则按失败/超时处理。
    """
    import public

    deadline = time.time() + DEPENDENCY_INSTALL_TIMEOUT
    started = time.time()
    while time.time() < deadline:
        cancelled()
        if guide.get_plugin_status(name, version):
            if progress:
                progress(slot_end, "{} is ready".format(display))
            return True
        if not int(public.M("tasks").where(
            "status!=? and name LIKE ?", ("1", "%" + name + "%")
        ).count() or 0):
            break
        ratio = slot_start + (time.time() - started) / DEPENDENCY_INSTALL_TIMEOUT * (slot_end - slot_start)
        if progress:
            progress(min(ratio, slot_end - 0.01), "Installing {}".format(display))
        time.sleep(2)
    if guide.get_plugin_status(name, version):
        return True
    statuses = public.M("tasks").where(
        "name LIKE ?", ("%" + name + "%",)
    ).field("id,name,status").select()
    detail = "; ".join(
        "task#{} [{}]".format(row.get("id"), row.get("status"))
        for row in statuses
    ) if isinstance(statuses, list) and statuses else "no task record"
    raise ProjectImportError(
        "{} installation failed or timed out ({}); install it in the aaPanel app store and retry".format(display, detail),
        "DEPENDENCY_INSTALL_FAILED",
    )


def _preflight(session, project_config):
    if session.get("status") not in ("analyzed", "importing"):
        raise ProjectImportError("Project analysis has not completed", "ANALYSIS_REQUIRED")
    source_root = safe_realpath(session.get("internal", {}).get("project_root", ""))
    if not os.path.isdir(source_root):
        raise ProjectImportError("Prepared project files no longer exist", "SOURCE_NOT_FOUND")
    source_mode = session.get("internal", {}).get("source_mode", "staged")
    project_type = str(project_config.get("project_type", session.get("analysis", {}).get("detected_project_type", ""))).lower()
    if project_type not in ("php", "static", "node"):
        raise ProjectImportError("Unsupported project type", "UNSUPPORTED_PROJECT_TYPE")
    destination = str(project_config.get("destination", "")).strip()
    if source_mode == "register":
        if destination and safe_realpath(destination) != source_root:
            raise ProjectImportError(
                "Local register mode must use the selected source directory",
                "LOCAL_REGISTER_PATH_MISMATCH",
            )
        destination = source_root
    else:
        destination = _validate_destination(destination)
        if os.path.exists(destination):
            raise ProjectImportError("Destination directory already exists", "DESTINATION_EXISTS")
        if _panel_site_id("path", destination):
            raise ProjectImportError(
                "The destination is already registered by an aaPanel project",
                "PROJECT_PATH_EXISTS",
            )
        project_name = _project_record_name(project_type, project_config)
        if project_name and _panel_site_id("name", project_name):
            raise ProjectImportError(
                "The aaPanel project name already exists: {}".format(project_name),
                "PROJECT_NAME_EXISTS",
            )
    if project_type in ("php", "static") and not str(project_config.get("domain", "")).strip():
        raise ProjectImportError("Domain name is required", "DOMAIN_REQUIRED")
    if project_type == "php" and not str(project_config.get("php_version", "")).strip():
        raise ProjectImportError("PHP runtime version is required", "PHP_RUNTIME_REQUIRED")
    if project_type == "php":
        prepare_php_config(project_config)
    if project_type == "node" and not str(project_config.get("runtime_version", project_config.get("nodejs_version", ""))).strip():
        raise ProjectImportError("Node.js runtime version is required", "NODE_RUNTIME_REQUIRED")
    if project_type == "node":
        prepare_node_config(project_config, source_root, install_runtime=False)
    if project_type == "python" and not str(project_config.get("python_bin", project_config.get("runtime_path", ""))).strip():
        raise ProjectImportError("Python runtime path is required", "PYTHON_RUNTIME_REQUIRED")
    return source_root, source_mode, destination, project_type


def _project_record_name(project_type, project_config):
    if project_type == "node":
        return str(project_config.get("project_name", "imported_node")).strip()
    if project_type == "python":
        return str(project_config.get("project_name", "imported_python")).strip()
    return ""


def _panel_site_id(field, value):
    if field not in ("name", "path") or not str(value or "").strip():
        return 0
    try:
        import public
        site_id = public.M("sites").where(
            "{}=?".format(field),
            (str(value).strip(),),
        ).getField("id")
        return int(site_id or 0)
    except Exception:
        return 0


def _validate_destination(destination):
    destination = safe_realpath(destination)
    blocked = ("/", "/boot", "/dev", "/etc", "/proc", "/root", "/run", "/sys", "/usr", "/var", "/www/server")
    if destination in blocked:
        raise ProjectImportError("This destination is not allowed", "DESTINATION_BLOCKED")
    parent = os.path.dirname(destination)
    if not parent or parent == destination:
        raise ProjectImportError("Invalid destination directory", "INVALID_DESTINATION")
    os.makedirs(parent, mode=0o755, exist_ok=True)
    return destination


def _commit_files(source, destination, task_id, progress, cancelled):
    temporary = destination + ".importing." + task_id
    if os.path.exists(temporary):
        shutil.rmtree(temporary, ignore_errors=True)
    copy_directory(source, temporary, progress=progress, cancelled=cancelled)
    cancelled()
    if os.path.exists(destination):
        shutil.rmtree(temporary, ignore_errors=True)
        raise ProjectImportError("Destination directory already exists", "DESTINATION_EXISTS")
    _normalize_site_ownership(temporary)
    os.replace(temporary, destination)
    return destination


def _normalize_site_ownership(root):
    """把提交的整棵站点树归一化为 www:www 所有，并修正目录/文件权限。

    copy_directory 用 shutil.copy2 拷贝，只保留源文件权限位，属主变成 root；
    PHP-FPM 以 www 用户运行，不修正会导致读取站点文件时 Permission denied
    （例如 wp-config.php / wp-settings.php 属主为 root 且权限异常）。
    """
    import public
    try:
        public.recursive_set_own(root, "www", "www")
    except Exception:
        pass
    for current, dirs, files in os.walk(root, followlinks=False):
        for dir_name in dirs:
            dir_path = os.path.join(current, dir_name)
            if os.path.islink(dir_path):
                continue
            try:
                os.chmod(dir_path, 0o755)
            except OSError:
                pass
        for file_name in files:
            file_path = os.path.join(current, file_name)
            if os.path.islink(file_path):
                continue
            try:
                mode = os.stat(file_path, follow_symlinks=False).st_mode
                os.chmod(file_path, 0o755 if (mode & 0o111) else 0o644)
            except OSError:
                pass


def _ssl_result(project_type, config, project_result=None):
    enabled = bool(config.get("ssl_enabled"))
    if not enabled:
        return {"enabled": False, "message": "SSL was not requested"}
    site_id = int((project_result or {}).get("site_id", 0) or 0)
    if project_type in ("php", "static") and site_id:
        try:
            # 与 php_site_clone_v2._apply_ssl 的降级路径一致：
            # 先 _prepare_site_domains 校验可申请证书的有效域名，再提交申请。
            # AddSite 内部的 ssl_auto 只有 get 带 pid 且 ssl_auto == "1" 时才会
            # 触发，导入建站前拿不到站点ID，所以这里拿到 site_id 后显式申请。
            from ssl_domainModelV2.service import _prepare_site_domains, smart_ssl
            domains = _prepare_site_domains(int(site_id))
            if not domains:
                return {
                    "enabled": True,
                    "requested": False,
                    "warning": "Automatic SSL skipped: no valid domain found. "
                               "Make sure the domain resolves to this server, then apply SSL manually.",
                    "message": "Automatic SSL skipped: no valid domain found",
                }
            from BTPanel import app
            with app.app_context():
                smart_ssl(int(site_id))
        except Exception as exc:
            return {
                "enabled": True,
                "requested": True,
                "warning": "Automatic SSL request failed: {}".format(exc),
                "message": "Automatic SSL request failed",
            }
        return {
            "enabled": True,
            "requested": True,
            "site_id": site_id,
            "domains": domains,
            "message": "Automatic SSL request was submitted for the site",
        }
    return {
        "enabled": True,
        "requested": False,
        "message": "Project created without automatic SSL",
        "warning": "Automatic SSL is not available for this project type in the first version.",
    }


def _health_check(project_result, project_path):
    if not os.path.isdir(project_path):
        return {"status": "warning", "warning": "Project directory is missing after import", "message": "Health check failed"}
    project_type = project_result.get("project_type")
    startup = project_result.get("startup", {})
    if project_type == "node" and startup.get("status") == "failed":
        return {
            "status": "warning",
            "warning": startup.get("warning", startup.get("message", "Node.js project failed to start")),
            "message": "Node.js project startup failed",
        }
    port = int(project_result.get("port", 0) or 0)
    if project_type in ("node", "python") and port:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        try:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return {
                    "status": "warning",
                    "warning": "The project was created but port {} is not listening yet".format(port),
                    "message": "Project process is not ready",
                }
        finally:
            sock.close()
    return {"status": "ok", "message": "Project health check completed"}
