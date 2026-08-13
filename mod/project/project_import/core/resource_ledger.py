# coding: utf-8

import os

from .json_store import atomic_write_json, read_json


class ResourceLedger:
    def __init__(self, path):
        self.path = path
        self.data = read_json(path, default={}) or {}

    def record(self, key, value):
        self.data[key] = value
        atomic_write_json(self.path, self.data)

    def append(self, key, value):
        self.data.setdefault(key, []).append(value)
        atomic_write_json(self.path, self.data)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def exists(self):
        return os.path.exists(self.path)

