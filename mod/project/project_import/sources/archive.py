# coding: utf-8

import os
import shutil

from .base import BaseSource, archive_base_name
from ..core.exceptions import ProjectImportError
from ..core.security import extract_archive, select_project_root


class ArchiveSource(BaseSource):
    def fetch(self):
        upload = self.session.get("upload", {})
        archive_path = upload.get("path", "")
        if not upload.get("completed") or not archive_path or not os.path.isfile(archive_path):
            raise ProjectImportError("Archive upload has not been completed", "UPLOAD_NOT_COMPLETED")
        destination = os.path.join(self.work_dir, "source")
        if os.path.exists(destination):
            shutil.rmtree(destination, ignore_errors=True)
        extract_archive(
            archive_path,
            destination,
            progress=lambda ratio, msg: self.reporter.update("fetch_source", ratio, msg),
            cancelled=self.check_cancelled,
        )
        return {
            "path": select_project_root(destination),
            "mode": "staged",
            "summary": os.path.basename(archive_path),
            "name": archive_base_name(archive_path),
        }

