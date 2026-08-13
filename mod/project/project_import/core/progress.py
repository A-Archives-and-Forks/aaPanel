# coding: utf-8

import time

from .constants import STEP_RUNNING, STEP_SUCCESS
from .exceptions import ImportTaskCancelled


class ProgressReporter:
    def __init__(self, store, task_id, weights):
        self.store = store
        self.task_id = task_id
        self.weights = dict(weights)
        self.order = list(weights.keys())
        self.last_write = 0.0

    def _total(self, key, ratio):
        total = 0.0
        for item in self.order:
            weight = float(self.weights[item])
            if item == key:
                total += weight * max(0.0, min(1.0, float(ratio)))
                break
            total += weight
        return min(99, int(total))

    def check_cancelled(self):
        if self.store.is_cancel_requested(self.task_id):
            raise ImportTaskCancelled()

    def start(self, key, message=""):
        self.check_cancelled()
        self.store.update_step(
            self.task_id, key, status=STEP_RUNNING, ps=message,
            progress=0, stage=key, total_progress=self._total(key, 0),
        )

    def update(self, key, ratio, message="", force=False):
        self.check_cancelled()
        now = time.monotonic()
        if not force and now - self.last_write < 0.35:
            return
        self.last_write = now
        percent = max(0, min(100, int(float(ratio) * 100)))
        self.store.update_step(
            self.task_id, key, status=STEP_RUNNING, ps=message,
            progress=percent, stage=key, total_progress=self._total(key, ratio),
        )

    def finish(self, key, message="Completed"):
        self.check_cancelled()
        self.store.update_step(
            self.task_id, key, status=STEP_SUCCESS, ps=message,
            progress=100, stage=key, total_progress=self._total(key, 1),
        )

