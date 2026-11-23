"""The preferences file: one JSON per instance, in its state folder, written whole and atomically."""

import json
import os
import threading
from pathlib import Path
from typing import Any

FILE_NAME = "preferences.json"
# keys an older file may still hold; never written back
LEGACY_KEYS = ("terminal",)


class PreferencesStore:
    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / FILE_NAME
        self._lock = threading.RLock()

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        part = self.path.with_suffix(".json.part")
        kept = {key: value for key, value in data.items() if key not in LEGACY_KEYS}
        part.write_text(json.dumps(kept, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(part, self.path)

    def load(self) -> dict[str, Any]:
        """The saved preferences with the defaults filled in."""
        with self._lock:
            data = self._read()
        identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
        return {
            "language": data.get("language", "en"),
            "identity": {
                "open_with": identity.get("open_with", "last"),
                "last": identity.get("last"),
                "agents": dict(identity.get("agents") or {}),
            },
        }

    def update(
        self,
        language: str | None = None,
        open_with: str | None = None,
        last_identity: str | None = None,
        agents: dict[str, str] | None = None,
    ) -> None:
        with self._lock:
            data = self._read()
            if language is not None:
                data["language"] = language
            if open_with is not None or last_identity is not None or agents is not None:
                identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
                if open_with is not None:
                    identity["open_with"] = open_with
                if last_identity is not None:
                    identity["last"] = last_identity
                for who, folder in (agents or {}).items():
                    kept = dict(identity.get("agents") or {})
                    if folder:
                        kept[who] = folder
                    else:
                        kept.pop(who, None)
                    identity["agents"] = kept
                data["identity"] = identity
            self._write(data)

    def agent_config(self, identity: str) -> str | None:
        """The identity's own agent config dir, when one is set."""
        return self.load()["identity"]["agents"].get(identity)
