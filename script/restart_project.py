# -*- coding: utf-8 -*-
# -----------------------------
# Website Project Restart Script
# -----------------------------
# author: aaPanel

import os
import sys
from importlib import import_module
from typing import Optional, Any

if "/www/server/panel" not in sys.path:
    sys.path.insert(0, '/www/server/panel')
if "/www/server/panel/class" not in sys.path:
    sys.path.insert(0, '/www/server/panel/class')
if "/www/server/panel/class_v2" not in sys.path:
    sys.path.insert(0, '/www/server/panel/class_v2')

os.chdir('/www/server/panel')

import public


def get_action_model_obj(model_name: str) -> Optional[Any]:
    try:
        if model_name == "java" and os.path.exists("/www/server/panel/mod/project/java/projectMod.py"):
            model = import_module("mod.project.java.projectMod")
        else:
            model = import_module(f"projectModelV2.{model_name}Model")
    except Exception as e:
        print(f"[ERROR] Failed to import module for '{model_name}': {e}")
        return None

    if not hasattr(model, "main"):
        return None
    main_class = getattr(model, "main")
    if not callable(main_class):
        return None
    return main_class()


def restart_project_based_on_model(model_name: str, project_name: str) -> bool:
    try:
        print(f"Starting to restart {model_name} project [{project_name}]...")
        model_obj = get_action_model_obj(model_name)

        if not model_obj:
            print(f"[ERROR] Could not load operation class for '{model_name}'.")
            return False

        # Execute aaPanel restart method
        res = model_obj.restart_project(public.to_dict_obj({
            "project_name": project_name
        }))

        # Safely evaluate aaPanel status response (handles True/False, 'success', or status code 0/1)
        is_success = False
        if isinstance(res, dict):
            status = res.get('status')
            if status is True or status == 0 or status == 'success':
                is_success = True

        if not is_success:
            msg = res.get('msg', 'No error message returned') if isinstance(res, dict) else str(res)
            print(f"[FAILED] Failed to restart project [{project_name}]. Details: {msg}")
            return False

        print(f"[SUCCESS] Project [{project_name}] restarted successfully!")
        return True

    except Exception as e:
        # print("[CRITICAL] Exception occurred during restart execution:")
        print(public.get_error_info())
        print(f"Error details: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: /www/server/panel/pyenv/bin/python restart_project.py <model_name> <project_name>")
        print("Example: /www/server/panel/pyenv/bin/python restart_project.py python my_website")
        sys.exit(1)

    model_arg = sys.argv[1].lower()
    project_arg = sys.argv[2]

    success = restart_project_based_on_model(model_arg, project_arg)
    if not success:
        sys.exit(1)