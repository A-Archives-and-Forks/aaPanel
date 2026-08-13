# coding: utf-8

import os
import shutil

from ..core.exceptions import ProjectImportError


# 按长度降序排列，先匹配 .tar.gz 等复合扩展名
ARCHIVE_EXTENSIONS = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz", ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz")


def archive_base_name(path):
    """从压缩包路径推断项目名：去掉扩展名，保留压缩包基础名。"""
    base = os.path.basename(path)
    lower = base.lower()
    for extension in ARCHIVE_EXTENSIONS:
        if lower.endswith(extension):
            return base[: -len(extension)]
    return os.path.splitext(base)[0]


class BaseSource:
    def __init__(self, session, config, work_dir, reporter):
        self.session = session
        self.config = config or {}
        self.work_dir = work_dir
        self.reporter = reporter

    def check_cancelled(self):
        self.reporter.check_cancelled()

    def fetch(self):
        raise NotImplementedError


def copy_directory(source, destination, progress=None, cancelled=None):
    if os.path.exists(destination):
        shutil.rmtree(destination, ignore_errors=True)
    os.makedirs(destination, mode=0o755, exist_ok=True)
    files = []
    for current, dirs, names in os.walk(source, followlinks=False):
        dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(current, name))]
        for name in names:
            path = os.path.join(current, name)
            if not os.path.islink(path):
                files.append(path)
    total = max(1, len(files))
    for index, path in enumerate(files, 1):
        if cancelled:
            cancelled()
        relative = os.path.relpath(path, source)
        target = os.path.join(destination, relative)
        os.makedirs(os.path.dirname(target), mode=0o755, exist_ok=True)
        shutil.copy2(path, target)
        if progress:
            progress(index / total, "Copying {}".format(relative.replace("\\", "/")))
    if not files and not os.path.isdir(source):
        raise ProjectImportError("Source directory does not exist", "SOURCE_NOT_FOUND")
    return destination

