# coding: utf-8

from .node import (
    NodeCreator,
    get_installed_nodejs_versions,
    prepare_node_config,
    prepare_node_runtime,
)
from .php import (
    PHPCreator,
    StaticCreator,
    get_installed_php_versions,
    prepare_php_config,
    prepare_php_runtime,
)
from .python import PythonCreator


CREATORS = {
    "php": PHPCreator,
    "static": StaticCreator,
    "node": NodeCreator,
    # "python": PythonCreator,
}


def get_creator(project_type, **kwargs):
    creator = CREATORS.get(str(project_type or "").lower())
    if creator is None:
        from ..core.exceptions import ProjectImportError
        raise ProjectImportError("Unsupported project type", "UNSUPPORTED_PROJECT_TYPE")
    return creator(**kwargs)


__all__ = [
    "get_creator",
    "get_installed_nodejs_versions",
    "get_installed_php_versions",
    "prepare_node_config",
    "prepare_node_runtime",
    "prepare_php_config",
    "prepare_php_runtime",
    "CREATORS",
]
