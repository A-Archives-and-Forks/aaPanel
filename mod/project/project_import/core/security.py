# coding: utf-8

import os
import stat
import tarfile
import zipfile

from .exceptions import ProjectImportError


MAX_ARCHIVE_FILES = 100000
MAX_EXPANDED_SIZE = 20 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200

# local 来源除了目录外，还接受本机已存在的压缩包文件路径
LOCAL_SOURCE_ARCHIVES = (".zip", ".tar", ".tar.gz", ".tgz")


def safe_realpath(path):
    if not path:
        raise ProjectImportError("Path cannot be empty", "PATH_REQUIRED")
    return os.path.realpath(os.path.abspath(str(path)))


def ensure_child_path(root, path):
    root = safe_realpath(root)
    path = safe_realpath(path)
    try:
        valid = os.path.commonpath([root, path]) == root
    except ValueError:
        valid = False
    if not valid:
        raise ProjectImportError("Path escapes the allowed directory", "PATH_TRAVERSAL")
    return path


def validate_local_source(path):
    path = safe_realpath(path)
    if os.path.isfile(path):
        if not path.lower().endswith(LOCAL_SOURCE_ARCHIVES):
            raise ProjectImportError(
                "Local source file must be a supported archive (.zip/.tar/.tar.gz/.tgz)",
                "UNSUPPORTED_ARCHIVE",
            )
        return path
    if not os.path.isdir(path):
        raise ProjectImportError("Local source directory does not exist", "SOURCE_NOT_FOUND")
    blocked = {
        "/", "/boot", "/dev", "/etc", "/proc", "/root", "/run", "/sys",
        "/usr", "/var", "/www", "/www/server", "/www/server/panel",
    }
    if path in blocked:
        raise ProjectImportError("This system directory cannot be imported", "SYSTEM_PATH_BLOCKED")
    return path


def _validate_archive_name(root, name):
    normalized = str(name or "").replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        raise ProjectImportError("Archive contains an absolute path", "UNSAFE_ARCHIVE")
    target = ensure_child_path(root, os.path.join(root, normalized))
    if target == safe_realpath(root):
        return target
    return target


def extract_archive(archive_path, destination, progress=None, cancelled=None):
    archive_path = safe_realpath(archive_path)
    destination = safe_realpath(destination)
    os.makedirs(destination, mode=0o700, exist_ok=True)
    lower = archive_path.lower()
    if lower.endswith(".zip"):
        return _extract_zip(archive_path, destination, progress, cancelled)
    if lower.endswith((".tar.gz", ".tgz", ".tar")):
        return _extract_tar(archive_path, destination, progress, cancelled)
    raise ProjectImportError("Unsupported archive format", "UNSUPPORTED_ARCHIVE")


def _extract_zip(archive_path, destination, progress, cancelled):
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_FILES:
            raise ProjectImportError("Archive contains too many files", "ARCHIVE_FILE_LIMIT")
        expanded = sum(max(0, int(item.file_size)) for item in members)
        packed = max(1, sum(max(0, int(item.compress_size)) for item in members))
        if expanded > MAX_EXPANDED_SIZE or expanded / packed > MAX_COMPRESSION_RATIO:
            raise ProjectImportError("Archive expansion limit exceeded", "ARCHIVE_SIZE_LIMIT")
        for index, member in enumerate(members, 1):
            if cancelled:
                cancelled()
            target = _validate_archive_name(destination, member.filename)
            mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ProjectImportError("Archive symbolic links are not allowed", "UNSAFE_ARCHIVE_LINK")
            if member.is_dir():
                os.makedirs(target, mode=0o755, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), mode=0o755, exist_ok=True)
                with archive.open(member, "r") as src, open(target, "wb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
            if progress:
                progress(index / max(1, len(members)), "Extracting {}".format(member.filename))
    return destination


def _extract_tar(archive_path, destination, progress, cancelled):
    with tarfile.open(archive_path, "r:*") as archive:
        members = archive.getmembers()
        if len(members) > MAX_ARCHIVE_FILES:
            raise ProjectImportError("Archive contains too many files", "ARCHIVE_FILE_LIMIT")
        expanded = sum(max(0, int(item.size)) for item in members if item.isfile())
        packed = max(1, os.path.getsize(archive_path))
        if expanded > MAX_EXPANDED_SIZE or expanded / packed > MAX_COMPRESSION_RATIO:
            raise ProjectImportError("Archive expansion limit exceeded", "ARCHIVE_SIZE_LIMIT")
        for index, member in enumerate(members, 1):
            if cancelled:
                cancelled()
            target = _validate_archive_name(destination, member.name)
            if member.issym() or member.islnk() or member.isdev():
                raise ProjectImportError("Archive links and device files are not allowed", "UNSAFE_ARCHIVE_LINK")
            if member.isdir():
                os.makedirs(target, mode=0o755, exist_ok=True)
            elif member.isfile():
                os.makedirs(os.path.dirname(target), mode=0o755, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    continue
                with source, open(target, "wb") as dst:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
            if progress:
                progress(index / max(1, len(members)), "Extracting {}".format(member.name))
    return destination


def select_project_root(path):
    path = safe_realpath(path)
    entries = [name for name in os.listdir(path) if name not in ("__MACOSX", ".DS_Store")]
    if len(entries) == 1:
        candidate = os.path.join(path, entries[0])
        if os.path.isdir(candidate):
            return safe_realpath(candidate)
    return path

