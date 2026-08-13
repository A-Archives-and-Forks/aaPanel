# coding: utf-8

import ftplib
import os
import posixpath
import shutil

import public
from .base import BaseSource
from ..core.exceptions import ProjectImportError
from ..core.security import select_project_root


class FTPSource(BaseSource):
    def fetch(self):
        host = str(self.config.get("host", "")).strip()
        port = int(self.config.get("port", 21) or 21)
        username = str(self.config.get("username", "anonymous"))
        password = str(self.config.get("password", ""))
        remote_path = str(self.config.get("remote_path", "/")) or "/"
        if not host:
            raise ProjectImportError("FTP host is required", "FTP_HOST_REQUIRED")
        destination = os.path.join(self.work_dir, "source")
        if os.path.exists(destination):
            shutil.rmtree(destination, ignore_errors=True)
        os.makedirs(destination, mode=0o755, exist_ok=True)
        try:
            with ftplib.FTP() as client:
                client.connect(host, port, timeout=20)
                client.login(username, password)
                files = self._walk(client, remote_path)
                total_bytes = max(1, sum(item[1] for item in files))
                completed = 0
                for remote_file, size in files:
                    self.check_cancelled()
                    relative = posixpath.relpath(remote_file, remote_path).lstrip("./")
                    target = os.path.join(destination, *relative.split("/"))
                    os.makedirs(os.path.dirname(target), mode=0o755, exist_ok=True)
                    with open(target, "wb") as handle:
                        def callback(chunk):
                            nonlocal completed
                            self.check_cancelled()
                            handle.write(chunk)
                            completed += len(chunk)
                            self.reporter.update(
                                "fetch_source", completed / total_bytes,
                                "Downloading {}".format(relative),
                            )
                        client.retrbinary("RETR " + remote_file, callback, blocksize=1024 * 256)
        except ftplib.all_errors as exc:
            raise ProjectImportError("FTP download failed: {}".format(exc), "FTP_DOWNLOAD_FAILED")
        return {
            "path": select_project_root(destination),
            "mode": "staged",
            "summary": "{}:{}{}".format(host, port, remote_path),
            "name": posixpath.basename(remote_path.rstrip("/")),
        }

    def _walk(self, client, root):
        result = []

        def visit(path):
            self.check_cancelled()
            try:
                entries = list(client.mlsd(path))
            except (ftplib.error_perm, AttributeError):
                entries = []
                current = client.pwd()
                try:
                    client.cwd(path)
                    for name in client.nlst():
                        entries.append((posixpath.basename(name), {}))
                finally:
                    client.cwd(current)
            for name, facts in entries:
                name = posixpath.basename(str(name or ""))
                if name in ("", ".", ".."):
                    continue

                full = posixpath.join(path, name)
                kind = facts.get("type", "")
                if kind == "dir":
                    visit(full)
                    continue
                if kind == "file":
                    result.append((full, int(facts.get("size", 0) or 0)))
                    continue
                current = client.pwd()
                try:
                    client.cwd(full)
                    client.cwd(current)
                    visit(full)
                except ftplib.error_perm:
                    try:
                        size = int(client.size(full) or 0)
                    except ftplib.all_errors:
                        size = 0
                    result.append((full, size))
        visit(root)
        return result

