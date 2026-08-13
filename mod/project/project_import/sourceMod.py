# coding: utf-8

import ftplib
import os
import posixpath
import stat
import shutil
import tempfile
import subprocess
import sys

if "/www/server/panel" not in sys.path:
    sys.path.insert(0, "/www/server/panel")
if "/www/server/panel/class" not in sys.path:
    sys.path.insert(0, "/www/server/panel/class")

import public

from mod.project.project_import.core.api_utils import error_response, parse_json_field
from mod.project.project_import.core.exceptions import ProjectImportError
from mod.project.project_import.core.security import validate_local_source
from mod.project.project_import.core.ssh_utils import (
    configure_host_key_policy,
    load_private_key,
    private_key_content,
)
from mod.project.project_import.sources.git import GitSource, normalize_git_config


class _NullReporter:
    def check_cancelled(self):
        return None



class main:
    def test_connection(self, get):
        try:
            source_type, config = self._request(get)
            if source_type == "local":
                path = validate_local_source(config.get("path", ""))
                result = {"connected": True, "path": path}
            elif source_type == "ftp":
                with self._ftp(config) as client:
                    result = {"connected": True, "path": client.pwd()}
            elif source_type in ("sftp", "ssh"):
                client = self._ssh(config)
                try:
                    with client.open_sftp() as sftp:
                        result = {"connected": True, "path": sftp.normalize(".")}
                finally:
                    client.close()
            elif source_type == "git":
                refs = self._git_refs(config)
                result = {
                    "connected": True,
                    "auth_type": refs["auth_type"],
                    "default_branch": refs["default_branch"],
                    "branch_count": len(refs["branches"]),
                }
            else:
                raise ProjectImportError("Unsupported source type", "UNSUPPORTED_SOURCE")
            return public.return_message(0, 0, result)
        except Exception as exc:
            return error_response(exc)

    def list_directory(self, get):
        try:
            source_type, config = self._request(get)
            path = str(get.get("path", config.get("remote_path", config.get("path", "/"))))
            if source_type == "local":
                root = validate_local_source(path)
                if os.path.isfile(root):
                    return public.return_message(0, 0, {"path": path, "entries": [], "is_file": True})
                entries = self._local_entries(root)
            elif source_type == "ftp":
                with self._ftp(config) as client:
                    entries = self._ftp_entries(client, path)
            elif source_type in ("sftp", "ssh"):
                client = self._ssh(config)
                try:
                    with client.open_sftp() as sftp:
                        entries = self._sftp_entries(sftp, path)
                finally:
                    client.close()
            else:
                raise ProjectImportError("Directory browsing is not supported for this source", "DIRECTORY_BROWSE_UNSUPPORTED")
            return public.return_message(0, 0, {"path": path, "entries": entries})
        except Exception as exc:
            return error_response(exc)

    def list_git_branches(self, get):
        try:
            source_type, config = self._request(get)
            if source_type != "git":
                raise ProjectImportError("source_type must be git", "INVALID_SOURCE_TYPE")
            return public.return_message(0, 0, self._git_refs(config))
        except Exception as exc:
            return error_response(exc)

    @staticmethod
    def _request(get):
        source_type = str(get.get("source_type", "")).strip().lower()
        if not source_type:
            raise ProjectImportError("source_type is required", "SOURCE_TYPE_REQUIRED")
        config = parse_json_field(get.get("source_config", "{}"), "source_config")
        if not isinstance(config, dict):
            raise ProjectImportError("source_config must be a JSON object", "INVALID_SOURCE_CONFIG")
        return source_type, config

    @staticmethod
    def _ftp(config):
        client = ftplib.FTP()
        client.connect(str(config.get("host", "")), int(config.get("port", 21) or 21), timeout=20)
        client.login(str(config.get("username", "anonymous")), str(config.get("password", "")))
        return client

    @staticmethod
    def _ssh(config):
        try:
            import paramiko
        except ImportError:
            raise ProjectImportError("Paramiko is not installed", "PARAMIKO_NOT_INSTALLED")
        client = paramiko.SSHClient()
        configure_host_key_policy(client, paramiko, config)
        options = {
            "hostname": str(config.get("host", "")),
            "port": int(config.get("port", 22) or 22),
            "username": str(config.get("username", "root")),
            "timeout": 20,
            "allow_agent": False,
            "look_for_keys": False,
        }
        key_content = private_key_content(config)
        if key_content:
            options["pkey"] = load_private_key(
                paramiko,
                key_content,
                config.get("passphrase"),
            )
        else:
            options["password"] = str(config.get("password", ""))
        client.connect(**options)
        return client

    @staticmethod
    def _local_entries(path):
        result = []
        for item in os.scandir(path):
            result.append({
                "name": item.name,
                "path": item.path,
                "type": "directory" if item.is_dir(follow_symlinks=False) else "file",
                "size": item.stat(follow_symlinks=False).st_size if item.is_file(follow_symlinks=False) else 0,
            })
        return sorted(result, key=lambda item: (item["type"] != "directory", item["name"].lower()))

    @staticmethod
    def _ftp_entries(client, path):
        result = []
        for name, facts in client.mlsd(path):
            if name in (".", ".."):
                continue
            result.append({
                "name": name,
                "path": posixpath.join(path.rstrip("/"), name),
                "type": "directory" if facts.get("type") == "dir" else "file",
                "size": int(facts.get("size", 0) or 0),
            })
        return sorted(result, key=lambda item: (item["type"] != "directory", item["name"].lower()))

    @staticmethod
    def _sftp_entries(sftp, path):
        result = []
        for item in sftp.listdir_attr(path):
            result.append({
                "name": item.filename,
                "path": posixpath.join(path.rstrip("/"), item.filename),
                "type": "directory" if stat.S_ISDIR(item.st_mode) else "file",
                "size": int(item.st_size or 0),
            })
        return sorted(result, key=lambda item: (item["type"] != "directory", item["name"].lower()))

    def _git_refs(self, config):
        config = normalize_git_config(config)
        repository = config["repository"]
        work_dir = tempfile.mkdtemp(prefix="project_import_git_")
        adapter = GitSource(
            session={},
            config=config,
            work_dir=work_dir,
            reporter=_NullReporter(),
        )
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        cleanup = []
        try:
            adapter._configure_auth(environment, cleanup)
            result = subprocess.run(
                ["git", "ls-remote", "--symref", repository, "HEAD", "refs/heads/*"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                env=environment,
                check=False,
            )
            if result.returncode != 0:
                raise ProjectImportError(
                    "Git connection failed: {}".format(adapter._redact(result.stderr.strip())[-1500:]),
                    "GIT_CONNECTION_FAILED",
                )
            default_branch = ""
            branches = []
            for line in result.stdout.splitlines():
                if line.startswith("ref: refs/heads/") and line.rstrip().endswith("\tHEAD"):
                    default_branch = line.split("ref: refs/heads/", 1)[1].rsplit("\tHEAD", 1)[0].strip()
                    continue
                if "\trefs/heads/" not in line:
                    continue
                branch = line.split("\trefs/heads/", 1)[1].strip()
                if branch and branch not in branches:
                    branches.append(branch)
            branches.sort(key=lambda item: item.lower())
            if default_branch in branches:
                branches.remove(default_branch)
                branches.insert(0, default_branch)
            return {
                "auth_type": config["auth_type"],
                "default_branch": default_branch,
                "branches": branches,
            }
            # return branches
        except subprocess.TimeoutExpired as exc:
            tail = ""
            stderr_part = getattr(exc, "stderr", None)
            if stderr_part:
                if isinstance(stderr_part, bytes):
                    stderr_part = stderr_part.decode("utf-8", errors="ignore")
                tail = adapter._redact(str(stderr_part).strip())[-1500:]
            message = "Git connection timed out"
            if tail:
                message += ": {}".format(tail)
            raise ProjectImportError(message, "GIT_CONNECTION_TIMEOUT")
        except FileNotFoundError:
            raise ProjectImportError("Git is not installed", "GIT_NOT_INSTALLED")
        finally:
            for path in cleanup:
                try:
                    os.remove(path)
                except OSError:
                    pass
            shutil.rmtree(work_dir, ignore_errors=True)
