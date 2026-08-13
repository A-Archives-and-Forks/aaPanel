# coding: utf-8

import json

from ..core.exceptions import ProjectImportError


class BaseCreator:
    def __init__(self, config, project_path):
        self.config = config or {}
        self.project_path = project_path

    def create(self):
        raise NotImplementedError

    @staticmethod
    def message_payload(result):
        if not isinstance(result, dict):
            return result
        message = result.get("message")
        if isinstance(message, dict):
            return message
        return result

    @classmethod
    def ensure_success(cls, result, fallback="Project creation failed"):
        if not isinstance(result, dict):
            raise ProjectImportError(fallback, "PROJECT_CREATE_FAILED")
        status = result.get("status")
        status_code = result.get("status_code")
        failed = status is False or status == -1
        if status is None:
            failed = (
                status_code is False
                or (
                    isinstance(status_code, (int, float))
                    and not isinstance(status_code, bool)
                    and status_code < 0
                )
            )
        if failed:
            raise ProjectImportError(
                cls.error_message(result, fallback),
                "PROJECT_CREATE_FAILED",
            )
        return cls.message_payload(result)

    @classmethod
    def error_message(cls, value, fallback="Project creation failed"):
        """Extract the useful message from old and v2 aaPanel responses."""
        if isinstance(value, str):
            return value.strip() or fallback
        if isinstance(value, (list, tuple)):
            for item in value:
                message = cls.error_message(item, "")
                if message:
                    return message
            return fallback
        if not isinstance(value, dict):
            return fallback
        for key in ("error_msg", "error", "result", "msg", "message", "data"):
            if key not in value:
                continue
            message = cls.error_message(value.get(key), "")
            if message:
                return message
        return fallback

    def domains(self):
        domain = str(self.config.get("domain", "")).strip()
        domains = self.config.get("domains", [])
        if isinstance(domains, str):
            try:
                domains = json.loads(domains)
            except ValueError:
                domains = [item.strip() for item in domains.split(",") if item.strip()]
        if not isinstance(domains, list):
            domains = []
        if domain and domain not in domains:
            domains.insert(0, domain)
        return domains
