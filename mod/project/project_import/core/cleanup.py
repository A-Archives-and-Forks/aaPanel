# coding: utf-8

import os
import shutil

from .security import ensure_child_path, safe_realpath


def remove_created_destination(destination, expected_parent=None):
    if not destination or not os.path.exists(destination):
        return
    destination = safe_realpath(destination)
    if expected_parent:
        ensure_child_path(expected_parent, destination)
    if os.path.isdir(destination):
        shutil.rmtree(destination, ignore_errors=True)
    else:
        os.remove(destination)

