# coding: utf-8

import json
import os

from .base import BaseCreator


class PythonCreator(BaseCreator):
    def create(self):
        import public
        from projectModelV2.pythonModel import main as PythonModel

        config = self.config
        requirement = str(config.get("requirement_path", ""))
        if requirement and not os.path.isabs(requirement):
            requirement = os.path.join(self.project_path, requirement)
        run_file = str(config.get("run_file", ""))
        if run_file and not os.path.isabs(run_file):
            run_file = os.path.join(self.project_path, run_file)
        args = public.to_dict_obj({
            "pjname": str(config.get("project_name", "imported_python")),
            "port": str(config.get("port", 8000)),
            "stype": str(config.get("run_method", "command")),
            "path": self.project_path,
            "user": str(config.get("run_user", "www")),
            "python_bin": str(config.get("python_bin", config.get("runtime_path", ""))),
            "requirement_path": requirement,
            "env_list": json.dumps(config.get("env_list", [])),
            "env_file": str(config.get("env_file", "")),
            "framework": str(config.get("framework", "python")),
            "project_cmd": str(config.get("start_command", "python app.py")),
            "xsgi": str(config.get("xsgi", "wsgi")),
            "rfile": run_file,
            "call_app": str(config.get("call_app", "app")),
            "auto_run": True,
            "initialize": str(config.get("initialize", "")),
            "logpath": str(config.get("log_path", "")),
        })
        model = PythonModel()
        result = model.CreateProject(args)
        payload = self.ensure_success(result)
        domains = self.domains()
        if domains:
            domain_result = model.AddProjectDomain(public.to_dict_obj({
                "name": args.pjname,
                "domains": [item if ":" in item else item + ":80" for item in domains],
            }))
            self.ensure_success(domain_result, "Failed to bind Python project domain")
        project_id = public.M("sites").where("name=?", (args.pjname,)).getField("id") or 0
        return {
            "site_id": int(project_id),
            "project_name": args.pjname,
            "domain": domains[0] if domains else "",
            "project_type": "python",
            "path": self.project_path,
            "port": int(args.port or 0),
            "raw": payload if isinstance(payload, dict) else {},
        }

