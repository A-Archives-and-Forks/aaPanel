# coding: utf-8

import os
import re
import shutil
import tempfile


def update_database_config(project_root, project_type, database):
    updated = []
    if project_type == "php" and os.path.isfile(os.path.join(project_root, "wp-config.php")):
        path = os.path.join(project_root, "wp-config.php")
        replacements = {
            "DB_NAME": database["name"],
            "DB_USER": database["user"],
            "DB_PASSWORD": database["password"],
            "DB_HOST": database.get("host", "127.0.0.1"),
        }
        _replace_wp_config(path, replacements)
        updated.append(path)
    elif project_type == "php" and os.path.isfile(os.path.join(project_root, "artisan")):
        path = os.path.join(project_root, ".env")
        if os.path.isfile(path):
            replacements = {
                "DB_HOST": database.get("host", "127.0.0.1"),
                "DB_DATABASE": database["name"],
                "DB_USERNAME": database["user"],
                "DB_PASSWORD": database["password"],
            }
            _replace_env(path, replacements)
            updated.append(path)
    return updated


def _backup(path):
    backup = path + ".aapanel-import.bak"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
    return backup


def _atomic_text_write(path, content):
    fd, tmp_path = tempfile.mkstemp(prefix=".project_import_", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _set_web_owner(tmp_path)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _set_web_owner(path):
    """让写入的配置文件归面板 web 用户(www)所有，并保证其可读。

    mkstemp 生成的文件属主为 root 且权限为 0600，PHP-FPM 以 www 用户运行，
    不修正会导致读取配置时 Permission denied。
    """
    import public
    try:
        public.set_own(path, "www", "www")
        os.chmod(path, 0o640)
    except Exception:
        pass


def _replace_wp_config(path, replacements):
    _backup(path)
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        content = handle.read()
    for key, value in replacements.items():
        pattern = re.compile(r"(define\(\s*['\"]{}['\"]\s*,\s*)['\"][^'\"]*['\"](\s*\)\s*;)".format(re.escape(key)))
        content = pattern.sub(lambda match: "{}'{}'{}".format(match.group(1), str(value).replace("'", "\\'"), match.group(2)), content)
    _atomic_text_write(path, content)


def _replace_env(path, replacements):
    _backup(path)
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        lines = handle.read().splitlines()
    output = []
    found = set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in replacements:
            output.append("{}={}".format(key, replacements[key]))
            found.add(key)
        else:
            output.append(line)
    for key, value in replacements.items():
        if key not in found:
            output.append("{}={}".format(key, value))
    _atomic_text_write(path, "\n".join(output) + "\n")

