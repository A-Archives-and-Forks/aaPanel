# coding: utf-8

import json
import os
import re
import time

from .base import BaseCreator
from ..core.constants import PHP_RUNTIME_VERSIONS, locks_dir
from ..core.exceptions import ProjectImportError
from ..core.json_store import file_lock


PHP_INSTALL_TIMEOUT = 900
PHP_ROOT = "/www/server/php"


def get_installed_php_versions(php_root=None):
    """Return PHP runtimes offered by the import wizard.

    Installed versions are discovered from the filesystem under
    ``<php_root>/<version>/bin/php``. The bundled default versions are always
    included (``installed=False`` when missing) so the wizard can auto-install
    them later. Optional arguments and environment variables make the
    filesystem scan testable without changing production paths.
    """
    php_root = php_root or os.environ.get("AAPANEL_PHP_ROOT", PHP_ROOT)
    installed = set()
    if os.path.isdir(php_root):
        for version in os.listdir(php_root):
            if os.path.isfile(os.path.join(php_root, version, "bin", "php")):
                installed.add(version)
    values = set(PHP_RUNTIME_VERSIONS) | installed
    options = [{
        "label": _display_version(version),
        "value": version,
        "installed": version in installed,
    } for version in values]
    options.sort(key=lambda item: _php_version_sort_key(item["value"]), reverse=True)
    return options


def _php_version_sort_key(version):
    numbers = re.findall(r"\d+", str(version))
    return (int(numbers[0]) if numbers else 0,)


def prepare_php_config(config):
    """Validate and normalize the selected PHP runtime."""
    version = str(config.get("php_version", "")).strip().replace(".", "")
    installed = [
        item["value"]
        for item in get_installed_php_versions()
        if item.get("installed")
    ]
    if version not in PHP_RUNTIME_VERSIONS and version not in installed:
        supported = sorted(
            set(PHP_RUNTIME_VERSIONS) | set(installed),
            key=_php_version_sort_key,
            reverse=True,
        )
        raise ProjectImportError(
            "Unsupported PHP runtime '{}'; supported versions: {}".format(
                version, ", ".join(supported),
            ),
            "PHP_RUNTIME_UNSUPPORTED",
        )
    config["php_version"] = version
    return config


def prepare_php_runtime(config, progress=None):
    """Queue installation of the selected PHP runtime and wait until it is usable."""
    import public
    from panel_guide_page import GuidePage

    prepare_php_config(config)
    version = config["php_version"]
    php_bin = os.path.join(
        public.GetConfigValue("setup_path"),
        "php", version, "bin", "php",
    )
    with file_lock(os.path.join(locks_dir(), "php_runtime.install.lock")):
        _report_runtime(progress, 0.05, "Checking PHP {}".format(_display_version(version)))
        if os.path.isfile(php_bin):
            _report_runtime(progress, 1, "PHP {} is ready".format(_display_version(version)))
            return version

        deadline = time.time() + PHP_INSTALL_TIMEOUT
        while _active_php_install_count(public):
            if os.path.isfile(php_bin):
                _report_runtime(progress, 1, "PHP {} is ready".format(_display_version(version)))
                return version
            if time.time() >= deadline:
                raise ProjectImportError(
                    "Timed out waiting for another PHP installation task",
                    "PHP_RUNTIME_INSTALL_TIMEOUT",
                )
            _report_runtime(progress, 0.1, "Waiting for the current PHP installation task")
            time.sleep(2)

        _report_runtime(progress, 0.15, "Installing PHP {}".format(_display_version(version)))
        if not GuidePage().add_soft_install_task("php", version):
            raise ProjectImportError(
                "Failed to queue PHP {} installation".format(_display_version(version)),
                "PHP_RUNTIME_INSTALL_FAILED",
            )

        started_at = time.time()
        while time.time() < deadline:
            if os.path.isfile(php_bin):
                _report_runtime(progress, 1, "PHP {} is ready".format(_display_version(version)))
                return version
            if not _active_php_install_count(public):
                break
            elapsed = time.time() - started_at
            ratio = min(0.95, 0.15 + (elapsed / PHP_INSTALL_TIMEOUT) * 0.8)
            _report_runtime(progress, ratio, "Installing PHP {}".format(_display_version(version)))
            time.sleep(2)

        if time.time() >= deadline:
            raise ProjectImportError(
                "PHP {} installation timed out".format(_display_version(version)),
                "PHP_RUNTIME_INSTALL_TIMEOUT",
            )
        raise ProjectImportError(
            "PHP {} installation completed without a usable PHP binary".format(
                _display_version(version),
            ),
            "PHP_RUNTIME_INSTALL_INCOMPLETE",
        )


def _active_php_install_count(public):
    return int(public.M("tasks").where(
        "status!=? and name LIKE ?",
        ("1", "%php%"),
    ).count() or 0)


def _display_version(version):
    return "{}.{}".format(version[0], version[1:])


def _report_runtime(progress, ratio, message):
    if progress:
        progress(ratio, message)


class PHPCreator(BaseCreator):
    static = False

    def create(self):
        import public
        from panel_site_v2 import panelSite

        domains = self.domains()
        if not domains:
            raise ProjectImportError("Domain name is required", "DOMAIN_REQUIRED")
        primary = domains[0]
        domain_list = []
        for domain in domains[1:]:
            domain_list.append(domain if ":" in domain else domain + ":80")
        args = public.to_dict_obj({
            "webname": json.dumps({"domain": primary, "domainlist": domain_list, "count": len(domain_list)}),
            "type": "PHP",
            "ps": str(self.config.get("project_name", primary)),
            "path": self.project_path,
            "version": "00" if self.static else str(self.config.get("php_version", "83")),
            "sql": "",
            "datapassword": "",
            "datauser": "",
            "codeing": "utf8mb4",
            "port": "80",
            "type_id": 0,
            "force_ssl": 0,
            "ftp": False,
            "is_create_default_file": False,
            "ssl_auto": 1 if self.config.get("ssl_enabled") else 0,
            "sub_dir": "",
            "project_type": "PHP",
        })
        result = panelSite().AddSite(args)
        payload = self.ensure_success(result)
        site_id = payload.get("siteId", payload.get("id", 0)) if isinstance(payload, dict) else 0
        warnings = []
        install_warning = self._install_composer_dependencies()
        if install_warning:
            warnings.append(install_warning)
        return {
            "site_id": int(site_id or 0),
            "project_name": primary,
            "domain": primary,
            "project_type": "static" if self.static else "php",
            "path": self.project_path,
            "ssl_requested": bool(self.config.get("ssl_enabled")),
            "warnings": warnings,
            "raw": payload if isinstance(payload, dict) else {},
        }

    def _install_composer_dependencies(self):
        """Install composer dependencies after the site is created when requested.

        A failed install is downgraded to a warning; the site remains usable and
        the user can install the dependencies manually later.
        """
        if self.static:
            return ""
        if not bool(self.config.get("install_dependencies", True)):
            return ""
        composer_json = os.path.join(self.project_path, "composer.json")
        if not os.path.isfile(composer_json):
            return ""
        if os.path.isdir(os.path.join(self.project_path, "vendor")):
            return ""
        import public
        php_bin = os.path.join(
            public.GetConfigValue("setup_path"),
            "php", str(self.config.get("php_version", "83")), "bin", "php",
        )
        composer_bin = "/usr/bin/composer"
        if not os.path.isfile(php_bin) or not os.path.isfile(composer_bin):
            return "Composer is not available; PHP dependencies were not installed"
        log_path = "/tmp/project_import_composer.log"
        command = (
            "cd {} && export COMPOSER_ALLOW_SUPERUSER=1 && "
            "{} {} install --no-interaction --no-progress > {} 2>&1".format(
                self.project_path, php_bin, composer_bin, log_path,
            )
        )
        public.ExecShell(command)
        vendor_path = os.path.join(self.project_path, "vendor")
        if os.path.isdir(vendor_path):
            # composer 以 root 运行，生成的 vendor 属主是 root，
            # PHP-FPM 以 www 用户运行，不修正会读取失败
            try:
                public.recursive_set_own(vendor_path, "www", "www")
            except Exception:
                pass
            return ""
        tail = public.readFile(log_path) or ""
        return "PHP dependencies may have failed to install; vendor directory was not created: {}".format(tail[-500:])


class StaticCreator(PHPCreator):
    static = True
