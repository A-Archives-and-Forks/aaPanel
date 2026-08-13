# coding: utf-8

import os
import shutil

from .base import BaseSource, archive_base_name, copy_directory
from ..core.security import extract_archive, select_project_root, validate_local_source


class LocalSource(BaseSource):
    def fetch(self):
        source = validate_local_source(self.config.get("path", ""))
        mode = str(self.config.get("mode", "copy")).lower()
        if mode not in ("register", "copy"):
            mode = "copy"
        if mode == "register":
            if os.path.isfile(source):
                raise ProjectImportError(
                    "Register mode requires a local directory, not an archive file",
                    "LOCAL_REGISTER_FILE_NOT_ALLOWED",
                )
            self.reporter.update("fetch_source", 1, "Using the existing local directory", force=True)
            return {
                "path": source,
                "mode": "register",
                "summary": source,
                "name": os.path.basename(source.rstrip(os.sep)),
            }
        destination = os.path.join(self.work_dir, "source")
        if os.path.isfile(source):
            if os.path.exists(destination):
                shutil.rmtree(destination, ignore_errors=True)
            extract_archive(
                source,
                destination,
                progress=lambda ratio, msg: self.reporter.update("fetch_source", ratio, msg),
                cancelled=self.check_cancelled,
            )
            return {
                "path": select_project_root(destination),
                "mode": "staged",
                "summary": source,
                "name": archive_base_name(source),
            }
        copy_directory(
            source,
            destination,
            progress=lambda ratio, msg: self.reporter.update("fetch_source", ratio, msg),
            cancelled=self.check_cancelled,
        )
        return {
            "path": select_project_root(destination),
            "mode": "staged",
            "summary": source,
            "name": os.path.basename(source.rstrip(os.sep)),
        }

