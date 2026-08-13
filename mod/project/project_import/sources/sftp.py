# coding: utf-8

import os
import posixpath
import shutil
import stat

from .base import BaseSource
from ..core.exceptions import ProjectImportError
from ..core.security import select_project_root
from ..core.ssh_utils import configure_host_key_policy, load_private_key, private_key_content


class SFTPSource(BaseSource):
    def fetch(self):
        try:
            import paramiko
        except ImportError:
            raise ProjectImportError("Paramiko is not installed", "PARAMIKO_NOT_INSTALLED")
        host = str(self.config.get("host", "")).strip()
        port = int(self.config.get("port", 22) or 22)
        username = str(self.config.get("username", "root"))
        password = self.config.get("password")
        key_content = private_key_content(self.config)
        remote_path = str(self.config.get("remote_path", "/")) or "/"
        if not host:
            raise ProjectImportError("SSH host is required", "SSH_HOST_REQUIRED")
        destination = os.path.join(self.work_dir, "source")
        if os.path.exists(destination):
            shutil.rmtree(destination, ignore_errors=True)
        os.makedirs(destination, mode=0o755, exist_ok=True)
        client = paramiko.SSHClient()
        configure_host_key_policy(client, paramiko, self.config)
        connect = {
            "hostname": host,
            "port": port,
            "username": username,
            "timeout": 20,
            "allow_agent": False,
            "look_for_keys": False,
        }
        if key_content:
            connect["pkey"] = load_private_key(
                paramiko,
                key_content,
                self.config.get("passphrase"),
            )
        else:
            connect["password"] = password
        try:
            client.connect(**connect)
            with client.open_sftp() as sftp:
                files = self._walk(sftp, remote_path)
                total = max(1, sum(item[1] for item in files))
                completed = 0
                for remote_file, size in files:
                    self.check_cancelled()
                    relative = posixpath.relpath(remote_file, remote_path).lstrip("./")
                    target = os.path.join(destination, *relative.split("/"))
                    os.makedirs(os.path.dirname(target), mode=0o755, exist_ok=True)
                    with sftp.open(remote_file, "rb") as source, open(target, "wb") as output:
                        while True:
                            self.check_cancelled()
                            chunk = source.read(1024 * 256)
                            if not chunk:
                                break
                            output.write(chunk)
                            completed += len(chunk)
                            self.reporter.update(
                                "fetch_source", completed / total,
                                "Downloading {}".format(relative),
                            )
        except Exception as exc:
            raise ProjectImportError("SFTP download failed: {}".format(exc), "SFTP_DOWNLOAD_FAILED")
        finally:
            client.close()
        return {
            "path": select_project_root(destination),
            "mode": "staged",
            "summary": "{}:{}{}".format(host, port, remote_path),
            "name": posixpath.basename(remote_path.rstrip("/")),
        }

    def _walk(self, sftp, root):
        result = []

        def visit(path):
            self.check_cancelled()
            for item in sftp.listdir_attr(path):
                full = posixpath.join(path.rstrip("/"), item.filename)
                if stat.S_ISDIR(item.st_mode):
                    visit(full)
                elif stat.S_ISREG(item.st_mode):
                    result.append((full, int(item.st_size or 0)))
        visit(root)
        return result
