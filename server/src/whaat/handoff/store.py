"""What the page hands to a waiting session: a call whaat composed from the user's click, kept on disk until the
session's `whaat wait <kind>` takes it, so a server restart in between loses nothing. A call belongs to one piece of
work, the curation report or the migration plan the click was made on, and only a wait for that work takes it.
One file per identity in the state dir: per kind and work, the calls not taken yet and when a wait last asked."""

import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

Kind = Literal["curation", "migration"]
# a wait asks every few seconds (`whaat wait --every`, 3 s by default); one that asked within this long waits
WAIT_SECONDS = 15.0
# a call nobody took within this long belongs to a session that is gone: it is dropped, never run later
CALL_SECONDS = 600.0
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

    def waiting(self, identity: str, kind: Kind, work: str | None = None) -> bool:
        """Whether a session of this identity waits for this work right now; without `work`, for any of this kind."""
        with self._lock:
            works = self._load(identity).get(kind, {})
        asks = [works.get(work, {})] if work is not None else list(works.values())
        return any(self._clock() - float(entry.get("asked", 0)) < WAIT_SECONDS for entry in asks)

    def hand(self, identity: str, kind: Kind, work: str, call: str) -> bool:
        """Queue the call for the session waiting for this work; False, and nothing queued, when none waits."""
        if not self.waiting(identity, kind, work):
            return False
        with self._lock:
            data = self._load(identity)
            entry = data.setdefault(kind, {}).setdefault(work, {})
            entry["calls"] = [*entry.get("calls", []), {"call": call, "at": self._clock()}]
            self._save(identity, data)
        return True

    def take(self, identity: str, kind: Kind, work: str) -> str | None:
        """The oldest call for this work, removed as it is given, so two waits never get the same one. An ask that
        gets nothing marks the session as waiting; one that gets a call does not, since that wait ends with it."""
        with self._lock:
            data = self._load(identity)
            entry = data.setdefault(kind, {}).setdefault(work, {})
            now = self._clock()
            calls = [c for c in entry.get("calls", []) if now - float(c.get("at", 0)) < CALL_SECONDS]
            entry["calls"] = calls[1:]
            entry["asked"] = 0 if calls else now
            self._save(identity, data)
        return str(calls[0]["call"]) if calls else None
