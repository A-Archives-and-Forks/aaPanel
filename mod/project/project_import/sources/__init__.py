# coding: utf-8

from .archive import ArchiveSource
from .ftp import FTPSource
from .git import GitSource
from .local import LocalSource
from .sftp import SFTPSource


SOURCE_ADAPTERS = {
    "archive": ArchiveSource,
    "local": LocalSource,
    "git": GitSource,
    "ftp": FTPSource,
    "sftp": SFTPSource,
    "ssh": SFTPSource,
}


def get_source_adapter(source_type, **kwargs):
    adapter = SOURCE_ADAPTERS.get(str(source_type or "").lower())
    if adapter is None:
        from ..core.exceptions import ProjectImportError
        raise ProjectImportError("Unsupported source type", "UNSUPPORTED_SOURCE")
    return adapter(**kwargs)


__all__ = ["get_source_adapter", "SOURCE_ADAPTERS"]

