"""What the page hands to a waiting session: a call whaat composed from the user's click, kept on disk until the
session's `whaat wait <kind>` takes it, so a server restart in between loses nothing. One file per identity in the
state dir: per kind, the calls not taken yet and when a wait last asked."""

import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

Kind = Literal["curation", "migration"]
# a wait asks every few seconds; one that asked within this long is listening
LISTEN_SECONDS = 15.0
HANDOFF_DIR = "handoff"


class HandoffStore:
    def __init__(self, state_dir: Path, clock: Callable[[], float] = time.time) -> None:
        self._dir = state_dir / HANDOFF_DIR
        self._clock = clock
        self._lock = threading.Lock()

    def _file(self, identity: str) -> Path:
        return self._dir / f"{identity}.json"

    def _load(self, identity: str) -> dict[str, Any]:
        try:
            data = json.loads(self._file(identity).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, identity: str, data: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        part = self._file(identity).with_suffix(".part")
        part.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(part, self._file(identity))

    def listening(self, identity: str, kind: Kind) -> bool:
        """Whether a session of this identity waits for a call of this kind right now."""
        with self._lock:
            asked = float(self._load(identity).get(kind, {}).get("asked", 0))
        return self._clock() - asked < LISTEN_SECONDS

    def put(self, identity: str, kind: Kind, call: str) -> None:
        with self._lock:
            data = self._load(identity)
            entry = data.setdefault(kind, {})
            entry["calls"] = [*entry.get("calls", []), call]
            self._save(identity, data)

    def take(self, identity: str, kind: Kind) -> str | None:
        """The oldest call not taken yet, removed as it is given, so two waits never get the same one; the ask is
        stamped either way."""
        with self._lock:
            data = self._load(identity)
            entry = data.setdefault(kind, {})
            calls = entry.get("calls", [])
            entry["asked"] = self._clock()
            entry["calls"] = calls[1:]
            self._save(identity, data)
        return calls[0] if calls else None
