# coding: utf-8

import json
import os

from .exceptions import ProjectImportError
from .security import safe_realpath


SKIP_DIRS = {".git", ".svn", ".hg", "node_modules", "vendor", "__pycache__", ".venv", "venv"}
MAX_SCAN_FILES = 25000
MAX_SCAN_DEPTH = 12

# 所有来源都会暂存到 work_dir/source，这些通用名不能作为项目名
GENERIC_STAGING_NAMES = {"source", "staged", "project", "root"}


class ProjectDetector:
    def __init__(self, root, name_hint=""):
        self.root = safe_realpath(root)
        self.name_hint = str(name_hint or "").strip()
        self.files = []
        self.relative = set()
        self.total_size = 0

    def scan(self, progress=None, cancelled=None):
        self._collect(progress, cancelled)
        result = self._detect()
        result["sql_files"] = self._find_sql_files()
        result["stats"] = {
            "file_count": len(self.files),
            "total_size": self.total_size,
        }
        return result

    def _collect(self, progress, cancelled):
        base_depth = self.root.rstrip(os.sep).count(os.sep)
        for current, dirs, files in os.walk(self.root, followlinks=False):
            if cancelled:
                cancelled()
            depth = current.rstrip(os.sep).count(os.sep) - base_depth
            dirs[:] = [
                name for name in dirs
                if name not in SKIP_DIRS and depth < MAX_SCAN_DEPTH
                and not os.path.islink(os.path.join(current, name))
            ]
            for name in files:
                path = os.path.join(current, name)
                if os.path.islink(path):
                    continue
                relative = os.path.relpath(path, self.root).replace("\\", "/")
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                self.files.append((relative, path, size))
                self.relative.add(relative.lower())
                self.total_size += size
                if len(self.files) >= MAX_SCAN_FILES:
                    raise ProjectImportError("Project contains too many files to analyze", "SCAN_FILE_LIMIT")
                if progress and len(self.files) % 100 == 0:
                    progress(min(0.95, len(self.files) / MAX_SCAN_FILES), "Scanning project files")
        if progress:
            progress(1, "Project scan completed")

    def _has_name(self, name):
        name = name.lower()
        return name in self.relative or any(item.endswith("/" + name) for item in self.relative)

    def _has_extension(self, extension):
        return any(item.endswith(extension) for item in self.relative)

    def _detect(self):
        strong_php = self._has_name("wp-config.php") or self._has_name("artisan")
        has_php = strong_php or self._has_name("composer.json") or self._has_extension(".php")
        has_node = self._has_name("package.json")
        strong_python = self._has_name("manage.py") or self._has_name("pyproject.toml")
        has_python = strong_python or self._has_name("requirements.txt") or self._has_name("pipfile")
        has_static = self._has_name("index.html")

        candidates = []
        if has_php:
            candidates.append("php")
        if has_node:
            candidates.append("node")
        if has_python:
            candidates.append("python")
        if has_static:
            candidates.append("static")

        if strong_php:
            detected = "php"
        elif has_node and not strong_python:
            detected = "node"
        elif strong_python:
            detected = "python"
        elif has_php:
            detected = "php"
        elif has_static:
            detected = "static"
        else:
            detected = "static"

        warnings = []
        runtime_candidates = [item for item in candidates if item != "static"]
        if len(set(runtime_candidates)) > 1:
            warnings.append("Multiple project types were detected. Please confirm the project type manually.")
        if not candidates:
            warnings.append("No clear runtime marker was found. Static website was selected as the default.")

        return {
            "detected_project_type": detected,
            "project_type_candidates": list(dict.fromkeys(candidates)),
            "suggested_config": self._suggest(detected),
            "warnings": warnings,
        }

    def _suggest(self, detected):
        root_name = os.path.basename(self.root.rstrip(os.sep)) or ""
        name = self.name_hint
        if root_name and root_name.lower() not in GENERIC_STAGING_NAMES:
            # 优先使用真实目录名（保留压缩包单目录解包的场景），
            # 仅当根目录是 source 等通用暂存目录名时回退到来源提供的名称
            name = root_name
        result = {"project_name": self._safe_name(name)}
        if detected == "node":
            package_path = self._find_file("package.json")
            package = self._read_json(package_path)
            scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
            script = "start" if "start" in scripts else next(iter(scripts), "start")
            result.update({
                "package_manager": self._detect_package_manager(),
                "project_script": script,
                "start_command": "{} run {}".format(self._detect_package_manager(), script),
                "port": 3000,
            })
        elif detected == "python":
            requirement = self._find_file("requirements.txt") or self._find_file("pyproject.toml")
            result.update({
                "requirement_path": os.path.relpath(requirement, self.root).replace("\\", "/") if requirement else "",
                "run_method": "command",
                "start_command": self._suggest_python_command(),
                "port": 8000,
            })
        elif detected == "php":
            result.update({"php_version": "83"})
        return result

    @staticmethod
    def _safe_name(name):
        value = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
        return value.strip("_")[:64] or "imported_project"

    def _find_file(self, name):
        name = name.lower()
        candidates = [(rel.count("/"), path) for rel, path, _ in self.files if rel.lower().endswith(name)]
        return min(candidates)[1] if candidates else ""

    @staticmethod
    def _read_json(path):
        if not path:
            return {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError, UnicodeError):
            return {}

    def _detect_package_manager(self):
        if self._has_name("pnpm-lock.yaml"):
            return "pnpm"
        if self._has_name("yarn.lock"):
            return "yarn"
        return "npm"

    def _suggest_python_command(self):
        if self._has_name("manage.py"):
            return "python manage.py runserver 0.0.0.0:8000"
        for candidate in ("app.py", "main.py", "server.py"):
            if self._has_name(candidate):
                return "python {}".format(candidate)
        return "python app.py"

    def _find_sql_files(self):
        result = []
        for relative, absolute, size in self.files:
            lower = relative.lower()
            if lower.endswith(".sql") or lower.endswith(".sql.gz"):
                result.append({
                    "id": "sql_{}".format(len(result) + 1),
                    "name": relative,
                    "path": absolute,
                    "size": size,
                })
            if len(result) >= 50:
                break
        return result

