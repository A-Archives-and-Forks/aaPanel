# coding: utf-8

import os
import re
import shlex
import shutil
import stat
import subprocess
import time
import urllib.parse

from .base import BaseSource
from ..core.api_utils import bool_value
from ..core.exceptions import ProjectImportError
from ..core.security import select_project_root


GIT_AUTH_TYPES = ("public", "ssh_key", "token")
GIT_SSH_ROOT = "/root/.ssh"


def normalize_git_config(config):
    """Validate Git source settings and return a normalized secret config."""
    config = dict(config or {})
    repository = str(config.get("repository", "")).strip()
    auth_type = str(config.get("auth_type", "public")).strip().lower()
    branch = str(config.get("branch", "")).strip()
    if auth_type =='none':
        auth_type = "public"

    if not repository:
        raise ProjectImportError("Git repository is required", "GIT_REPOSITORY_REQUIRED")
    if any(char.isspace() for char in repository):
        raise ProjectImportError("Git repository URL is invalid", "GIT_REPOSITORY_INVALID")
    if auth_type not in GIT_AUTH_TYPES:
        raise ProjectImportError(
            "Unsupported Git authentication type: {}".format(auth_type),
            "GIT_AUTH_TYPE_UNSUPPORTED",
        )

    transport = _repository_transport(repository)
    if transport == "unknown":
        raise ProjectImportError("Git repository URL is invalid", "GIT_REPOSITORY_INVALID")
    if transport in ("http", "https") and _repository_has_credentials(repository):
        raise ProjectImportError(
            "Do not include credentials in the Git repository URL",
            "GIT_REPOSITORY_CREDENTIALS_FORBIDDEN",
        )

    normalized = {
        "repository": repository,
        "branch": branch,
        "auth_type": auth_type,
    }
    if auth_type == "public":
        if transport not in ("http", "https"):
            raise ProjectImportError(
                "Public Git repositories must use an HTTP or HTTPS URL",
                "GIT_AUTH_REPOSITORY_MISMATCH",
            )
    elif auth_type == "token":
        if transport != "https":
            raise ProjectImportError(
                "Token authentication requires an HTTPS repository URL",
                "GIT_AUTH_REPOSITORY_MISMATCH",
            )
        username = str(config.get("username", "")).strip()
        token = str(config.get("token", ""))
        if not username:
            raise ProjectImportError("Git username is required", "GIT_USERNAME_REQUIRED")
        if not token:
            raise ProjectImportError("Git personal access token is required", "GIT_TOKEN_REQUIRED")
        normalized["username"] = username
        normalized["token"] = token
    else:
        if transport != "ssh":
            raise ProjectImportError(
                "SSH key authentication requires an SSH repository URL",
                "GIT_AUTH_REPOSITORY_MISMATCH",
            )
        key_path = _validate_ssh_key_path(config.get("key_path", ""))
        normalized["key_path"] = key_path
        normalized["strict_host_key"] = bool_value(config.get("strict_host_key"), False)
    return normalized


def _repository_transport(repository):
    if re.match(r"^[A-Za-z0-9._-]+@[^\s:/]+:.+$", repository):
        return "ssh"
    parsed = urllib.parse.urlsplit(repository)
    if parsed.scheme == "ssh" and parsed.hostname:
        return "ssh"
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return "https" if parsed.scheme == "https" else "http"
    return "unknown"


def _repository_has_credentials(repository):
    parsed = urllib.parse.urlsplit(repository)
    return parsed.username is not None or parsed.password is not None


def _repository_name(repository):
    """从 Git 仓库地址推断项目名（用于分析结果的 suggested_config.project_name）。"""
    if "://" not in repository and "@" in repository:
        # scp-like: git@host:org/repo.git
        name = repository.rsplit(":", 1)[-1]
    else:
        parsed = urllib.parse.urlsplit(repository)
        name = parsed.path or repository
    name = name.rstrip("/").rsplit("/", 1)[-1]
    return name.rstrip(".git") or ""


def _validate_ssh_key_path(value):
    key_path = os.path.realpath(str(value or "").strip())
    ssh_root = os.path.realpath(GIT_SSH_ROOT)
    try:
        inside_root = os.path.commonpath((ssh_root, key_path)) == ssh_root
    except ValueError:
        inside_root = False
    if not key_path or not inside_root or key_path.endswith(".pub"):
        raise ProjectImportError(
            "Git SSH key must be a private key under /root/.ssh",
            "GIT_SSH_KEY_PATH_INVALID",
        )
    if not os.path.isfile(key_path):
        raise ProjectImportError("Git SSH private key does not exist", "GIT_SSH_KEY_NOT_FOUND")
    if not os.path.isfile(key_path + ".pub"):
        raise ProjectImportError(
            "The public key for the selected Git SSH key does not exist",
            "GIT_SSH_PUBLIC_KEY_NOT_FOUND",
        )
    return key_path


class GitSource(BaseSource):
    PROGRESS_RE = re.compile(r"(?:Receiving objects|Resolving deltas|Compressing objects):\s+(\d+)%")

    def fetch(self):
        self.config = normalize_git_config(self.config)
        repository = self.config["repository"]
        branch = self.config["branch"]
        destination = os.path.join(self.work_dir, "source")
        if os.path.exists(destination):
            shutil.rmtree(destination, ignore_errors=True)

        command = ["git", "clone", "--progress"]
        if _repository_transport(repository) in ("http", "https"):
            # curl 16 HTTP2 framing layer 错误：部分 git/curl 与远端 HTTP/2 协商不稳，
            # 会导致 clone 卡住/失败，强制 HTTP/1.1 规避
            command.extend(["-c", "http.version=HTTP/1.1"])
        if branch:
            command.extend(["--branch", branch, "--single-branch"])
        command.extend([repository, destination])
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        cleanup = []
        try:
            self._configure_auth(environment, cleanup)
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=environment,
                start_new_session=True,
            )
            started = time.time()
            output_tail = []
            while True:
                self.check_cancelled()
                line = process.stdout.readline() if process.stdout else ""
                if line:
                    clean = self._redact(line.strip())
                    output_tail.append(clean)
                    output_tail = output_tail[-20:]
                    match = self.PROGRESS_RE.search(clean)
                    ratio = int(match.group(1)) / 100 if match else min(0.95, (time.time() - started) / 300)
                    self.reporter.update("fetch_source", ratio, clean or "Cloning repository")
                if process.poll() is not None:
                    break
                if time.time() - started > 3600:
                    process.terminate()
                    raise ProjectImportError("Git clone timed out", "GIT_CLONE_TIMEOUT")
                if not line:
                    time.sleep(0.1)
            if process.returncode != 0 or not os.path.isdir(os.path.join(destination, ".git")):
                raise ProjectImportError(
                    "Git clone failed: {}".format("\n".join(output_tail)[-2000:]),
                    "GIT_CLONE_FAILED",
                )
            self.reporter.update("fetch_source", 1, "Repository cloned", force=True)
            return {
                "path": select_project_root(destination),
                "mode": "staged",
                "summary": repository,
                "name": _repository_name(repository),
            }
        except FileNotFoundError:
            raise ProjectImportError("Git is not installed", "GIT_NOT_INSTALLED")
        finally:
            for path in cleanup:
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _configure_auth(self, environment, cleanup):
        self.config = normalize_git_config(self.config)
        auth_type = self.config["auth_type"]
        if auth_type == "ssh_key":
            strict_value = "yes" if self.config.get("strict_host_key") else "accept-new"
            environment["HOME"] = "/root"
            environment["GIT_SSH_COMMAND"] = (
                "ssh -i {} -o IdentitiesOnly=yes -o BatchMode=yes "
                "-o StrictHostKeyChecking={} "
                "-o UserKnownHostsFile=/root/.ssh/known_hosts"
            ).format(
                shlex.quote(self.config["key_path"]),
                strict_value,
            )
            return
        if auth_type != "token":
            return
        username = self.config["username"]
        password = self.config["token"]
        auth_dir = os.path.join(self.work_dir, ".git_auth")
        os.makedirs(auth_dir, mode=0o700, exist_ok=True)
        user_file = os.path.join(auth_dir, "username")
        pass_file = os.path.join(auth_dir, "password")
        askpass = os.path.join(auth_dir, "askpass.sh")
        for path, value in ((user_file, username), (pass_file, password)):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(value)
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            cleanup.append(path)
        with open(askpass, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\ncase \"$1\" in *sername*) cat '{}';; *) cat '{}';; esac\n".format(user_file, pass_file))
        os.chmod(askpass, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        cleanup.append(askpass)
        environment["GIT_ASKPASS"] = askpass
        environment["GIT_ASKPASS_REQUIRE"] = "force"

    def _redact(self, text):
        result = str(text)
        for key in ("token",):
            value = str(self.config.get(key, ""))
            if value:
                result = result.replace(value, "***")
        return result


def bind_site_git(site_id, project_path, git_bind):
    """把 ssh_key 认证导入的 git 项目登记到 git 管理器（git_sites_auth 表），确保 git 管理器可用。

    仅兼容 ssh_key 认证方式；public / token 等 git 管理器升级后再做兼容。
    写法对齐 git_tools.GitTools.import_existing_repository：写 safe.directory、
    配置 core.sshCommand、插入 git_sites_auth 记录。失败返回 warning，不阻断导入。
    """
    repo = str(git_bind.get("repo", "")).strip()
    branch = str(git_bind.get("branch", "")).strip()
    auth_type = str(git_bind.get("auth_type", "ssh")).strip().lower()
    if auth_type == "ssh_key":
        auth_type = "ssh"
    key_path = str(git_bind.get("key_path", "")).strip()
    username = str(git_bind.get("username", "")).strip()
    token_encrypted = str(git_bind.get("token_encrypted", "")).strip()
    if not site_id or not repo or auth_type not in ("public", "ssh", "token"):
        return {"bound": False, "warning": "Git binding skipped: incomplete git bind information"}
    project_path = os.path.realpath(str(project_path or ""))
    if not os.path.isdir(os.path.join(project_path, ".git")):
        return {"bound": False, "warning": "Git binding skipped: the imported project has no .git directory"}
    if auth_type == "ssh" and (
        not os.path.isfile(key_path) or not os.path.isfile(key_path + ".pub")
    ):
        return {"bound": False, "warning": "Git binding skipped: the SSH private key does not exist"}
    if auth_type == "token" and (not username or not token_encrypted):
        return {"bound": False, "warning": "Git binding skipped: incomplete token authentication information"}

    try:
        import public
        if public.M("git_sites_auth").where("site_id=?", (int(site_id),)).count():
            return {"bound": False, "warning": "Git binding skipped: the site already has a git record"}

        custom_env = os.environ.copy()
        custom_env["HOME"] = "/root"
        custom_env["GIT_SAFE_DIRECTORY"] = "*"
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", project_path],
            env=custom_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=True,
        )
        if auth_type == "ssh":
            subprocess.run(
                [
                    "git", "-C", project_path, "config", "core.sshCommand",
                    "ssh -i {} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new".format(
                        shlex.quote(key_path)
                    ),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                check=True,
            )
        public.M("git_sites_auth").add(
            "site_id,repo,branch,auth_type,key_path,username,oauth_access_token,oauth_token_type",
            (
                int(site_id), repo, branch, auth_type, key_path, username,
                token_encrypted, "aes" if auth_type == "token" else "",
            ),
        )
        return {"bound": True, "warning": ""}
    except Exception as exc:
        return {"bound": False, "warning": "Git manager binding failed: {}".format(exc)}
