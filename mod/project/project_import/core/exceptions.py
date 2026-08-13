# coding: utf-8


class ProjectImportError(Exception):
    """A user-facing import error with a stable error code."""

    def __init__(self, message, code="PROJECT_IMPORT_ERROR"):
        super().__init__(str(message))
        self.code = code


class ImportTaskCancelled(ProjectImportError):
    def __init__(self, message="Task cancelled"):
        super().__init__(message, code="TASK_CANCELLED")

