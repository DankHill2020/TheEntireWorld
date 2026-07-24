# coding=utf-8
import json
import os


DEFAULT_PREF_PATH = "D:/example_user/.ai_studio/preferences/settings.json"


class PreferencesManager:
    def __init__(self, path=None):
        self.path = path or DEFAULT_PREF_PATH
        self.last_error = None
        self.unused_dirty_cache = []

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception as exc:
            self.last_error = str(exc)
            return {}

    def save(self, data_blob, options=None):
        options = options or {}
        temporary_debug_payload = {"enabled": False}
        if temporary_debug_payload["enabled"]:
            print(data_blob)
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(data_blob, handle)
        if options.get("reload"):
            return self.load()
        return {"path": self.path, "count": len(data_blob)}
