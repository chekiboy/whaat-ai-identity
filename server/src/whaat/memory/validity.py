"""memory-validity and memory-outcome on one identity's memory: scores, read and outcome logs, the Read hook's note.

A score starts at the `source` weight and loses 0.2 per 30 days since its anchor: the latest of `confirmed` and the
file's first commit, moved to each day it held. A use within 30 days of the previous one moves the anchor to that day; a
use after a longer silence moves it forward by one week only. A memory without a `source` weighs
0.9, or 0.8 when it is a codebase's fact or recipe (a repo dir's `project` or `reference`), which the code can outdate.
A superseded file without an index line is history and is not scored. The logs
(memory-reads.log, memory-outcomes.log: one tab-separated line per event) and memory-validity.json sit in the
identity's state dir. The personal dir is left out everywhere: it is not scored,
its reads are not logged, and its outcomes are not recorded.
"""

import datetime
import json
import os
import re
import subprocess
import tempfile

from whaat.memory.recall import DIR_MODE, LOG_NAME, PERSONAL, Roots, log_events

SOURCE_BASE: dict[str | None, float] = {"measured": 1.0, "user-decision": 1.0, "inference": 0.75, None: 0.9}
UNSET_CODE_BASE = 0.8
CODE_TYPES = ("project", "reference")
DECAY_DAYS = 30
DECAY_PER_DAY = 0.2 / DECAY_DAYS
HELD_AFTER_SILENCE_DAYS = 7
LEVELS = ((0.8, "certain"), (0.6, "likely"), (0.4, "uncertain"), (0.0, "stale"))
UNQUOTED_FIELDS = ("source", "confirmed", "supersedes")
SCORES_FILE = "memory-validity.json"
READS_LOG = "memory-reads.log"
OUTCOMES_LOG = "memory-outcomes.log"
OUTCOMES = ("held", "misled", "irrelevant")
MEMORY_MAP = "memory-map.md"
ORIGINS_FILE = "memory-origins.json"
STATE_DIR = "state"
PERSONAL_DIR = "personal"
WEAK_TRUTH = "⚠ Weak truthness: {why}."


class OutcomeError(ValueError):
    """A call memory-outcome would refuse, with its message."""


def _personal(rel: str) -> bool:
    return rel == PERSONAL_DIR or rel.startswith(PERSONAL_DIR + os.sep)


def git(directory: str, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", directory, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def parse(path: str) -> tuple[dict[str, str] | None, str]:
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not m:
        return None, text
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"\s*(\w+):\s*(.*)", line)
        if kv:
            value = kv.group(2).strip()
            fm.setdefault(kv.group(1), value.strip("\"'") if kv.group(1) in UNQUOTED_FIELDS else value)
    return fm, m.group(2)


def index_entries(idx: str) -> dict[str, str]:
    entries = {}
    if os.path.exists(idx):
        with open(idx, encoding="utf-8") as handle:
            for line in handle:
                m = re.match(r"\s*-\s*\[?([\w.-]+\.md)\]?(?:\([^)]*\))?\s*[—-]+\s*(.*)", line)
                if m:
                    entries[m.group(1)] = m.group(2).strip()
    return entries


def load_origins(store: str) -> dict[str, dict[str, str]]:
    """The source dates a migration carried in (state/memory-origins.json beside the memory dir): per path as it was
    imported, the source's first and last commit day and the import day."""
    try:
        with open(os.path.join(os.path.dirname(store), STATE_DIR, ORIGINS_FILE), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def commit_dates(store: str) -> tuple[dict[str, str], dict[str, str]]:
    """Per current path: the day it was first added and the day it last changed, as `commit_times` finds them."""
    added, last = commit_times(store)
    return {p: t[:10] for p, t in added.items()}, {p: t[:10] for p, t in last.items()}


def commit_times(store: str) -> tuple[dict[str, str], dict[str, str]]:
    """Per current path: when it was first added (followed across renames and moves) and when it last changed, as ISO
    commit times. `--relative` limits the log to the memory dir and names paths from it, as in a store that is its own
    repo. A file a migration brought in keeps its source's days: the import commit counts as neither its first nor its
    last change."""
    origins = load_origins(store)
    changes: list[tuple[str, list[str]]] = []
    current = None
    out = git(store, "log", "--relative", "-M", "--format=%x00%cI", "--name-status") or ""
    for line in out.splitlines():
        if line.startswith("\0"):
            current = line[1:]
        elif line and current:
            changes.append((current, line.split("\t")))
    added: dict[str, str] = {}
    last: dict[str, str] = {}
    for day, parts in reversed(changes):
        status, path = parts[0], parts[-1]
        if status.startswith("R") and len(parts) == 3:
            added[path] = added.pop(parts[1], day)
            last.pop(parts[1], None)
        elif status.startswith("D"):
            added.pop(path, None)
            last.pop(path, None)
            continue
        elif path not in added and (origin := origins.get(path)) and origin.get("imported") == day[:10]:
            added[path] = origin.get("added") or day
            last[path] = origin.get("last") or day
            continue
        else:
            added.setdefault(path, day)
        last[path] = day
    return added, last


def recall_outcomes(state: str, changed: dict[str, str]) -> tuple[dict[str, list[str]], dict[str, dict[str, int]]]:
    """From the outcome log, per memory name: the days it held, in order, and the outcome counts since the memory last
    changed, each session counted once per outcome."""
    path = os.path.join(state, OUTCOMES_LOG)
    held: dict[str, set[str]] = {}
    counts: dict[str, dict[str, int]] = {}
    seen: set[tuple[str, str, str]] = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 4:
                    continue
                day, outcome, rel, session = parts
                stem = os.path.basename(rel)[:-3]
                if stem not in changed:
                    continue
                if _after(day, changed[stem]) and (stem, outcome, session) not in seen:
                    seen.add((stem, outcome, session))
                    counts.setdefault(stem, {}).setdefault(outcome, 0)
                    counts[stem][outcome] += 1
                if outcome == "held":
                    held.setdefault(stem, set()).add(day[:10])
    return {stem: sorted(days) for stem, days in held.items()}, counts


def _after(event: str, change: str) -> bool:
    """An outcome logged after the change: by the second when both carry a time (the same second counts, as a commit
    and an outcome on it can share one), else by the day, strictly, since an outcome of the change's own day may have
    come before it."""
    if len(event) > 10 and len(change) > 10:
        return datetime.datetime.fromisoformat(event) >= datetime.datetime.fromisoformat(change)
    return event[:10] > change[:10]


def as_date(value: object) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def code_memory(rel: str, fm: dict[str, str]) -> bool:
    """A codebase's fact or recipe: a `project` or `reference` memory in a repo dir."""
    return len(rel.replace(os.sep, "/").split("/")) > 2 and fm.get("type") in CODE_TYPES


def source_weight(rel: str, fm: dict[str, str]) -> float:
    source = fm.get("source")
    if source and source in SOURCE_BASE:
        return SOURCE_BASE[source]
    return UNSET_CODE_BASE if code_memory(rel, fm) else SOURCE_BASE[None]


def misled_since_change(roots: Roots, rels: list[str]) -> set[str]:
    """Those of `rels` with a `misled` outcome since their own last commit."""
    _, changed = commit_times(roots.store)
    _, counts = recall_outcomes(str(roots.state), {os.path.basename(rel)[:-3]: changed.get(rel, "") for rel in rels})
    return {rel for rel in rels if counts.get(os.path.basename(rel)[:-3], {}).get("misled")}


def with_measured_source(text: str, day: str) -> str:
    """The memory's text with `source: measured` and `confirmed: <day>` in its frontmatter, replacing any earlier
    `source` or `confirmed` line."""
    m = re.match(r"(---\n)(.*?)(\n---\n?)(.*)", text, re.S)
    if not m:
        return text
    kept = [line for line in m.group(2).splitlines() if not re.match(r"\s*(source|confirmed):", line)]
    return m.group(1) + "\n".join([*kept, "source: measured", f"confirmed: {day}"]) + m.group(3) + m.group(4)


def anchor_day(start: list[str | None], held: list[str]) -> datetime.date | None:
    """The day a score's age counts from, as the module says; None with no start and no held day."""
    starts = [d for d in map(as_date, start) if d]
    used = sorted({d for d in map(as_date, held) if d})
    if not starts and not used:
        return None
    anchor = previous = max(starts) if starts else used[0]
    for day in used:
        if day > anchor:
            if (day - previous).days <= DECAY_DAYS:
                anchor = day
            else:
                anchor += datetime.timedelta(days=HELD_AFTER_SILENCE_DAYS)
        previous = max(previous, day)
    return anchor


def validity(
    rel: str, fm: dict[str, str], start: list[str | None], held: list[str], today: datetime.date
) -> tuple[float, str, int] | None:
    anchor = anchor_day(start, held)
    if anchor is None:
        return None
    age = (today - anchor).days
    score = max(0.0, source_weight(rel, fm) - DECAY_PER_DAY * age)
    return score, next(name for floor, name in LEVELS if score >= floor), age


def is_memory_file(directory: str, name: str, store: str) -> bool:
    if not name.endswith(".md") or name == "MEMORY.md":
        return False
    return name != MEMORY_MAP or os.path.realpath(directory) != os.path.realpath(store)


def personal_names_and_supersedes(personal: str) -> tuple[set[str], dict[str, str]]:
    """The personal dir's memory names, core included, and what its files supersede ({old name: `personal:<name>`}),
    so a store link to a personal memory resolves and a store file a personal memory supersedes is history."""
    stems: set[str] = set()
    superseded: dict[str, str] = {}
    for d, dirs, names in os.walk(personal):
        dirs[:] = sorted(x for x in dirs if not x.startswith("."))
        for n in sorted(names):
            if not is_memory_file(d, n, personal):
                continue
            stems.add(n[:-3])
            parsed, _ = parse(os.path.join(d, n))
            old = (parsed or {}).get("supersedes")
            if old:
                superseded.setdefault(old, f"{PERSONAL}{n[:-3]}")
    return stems, superseded


def score_store(store: str, state: str, today: datetime.date) -> dict[str, dict[str, object]]:
    """{rel path: entry} for every memory file outside the personal dir; history files carry `history`."""
    files: dict[str, tuple[dict[str, str], bool]] = {}
    for d, dirs, names in os.walk(store):
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and not (d == store and x == PERSONAL_DIR))
        index = index_entries(os.path.join(d, "MEMORY.md"))
        for n in sorted(x for x in names if is_memory_file(d, x, store)):
            rel = os.path.relpath(os.path.join(d, n), store)
            fm, _ = parse(os.path.join(d, n))
            files[rel] = (fm or {}, n in index)
    _, by_personal = personal_names_and_supersedes(os.path.join(store, PERSONAL_DIR))
    superseded = {
        **by_personal,
        **{fm["supersedes"]: rel for rel, (fm, _) in sorted(files.items()) if fm.get("supersedes")},
    }
    first, changed = commit_times(store)
    added = {p: t[:10] for p, t in first.items()}
    held, counts = recall_outcomes(state, {os.path.basename(p)[:-3]: changed.get(p, "") for p in files})
    entries: dict[str, dict[str, object]] = {}
    for rel, (fm, indexed) in sorted(files.items()):
        stem = os.path.basename(rel)[:-3]
        held_days = held.get(stem, [])
        anchors = {
            "confirmed": fm.get("confirmed"),
            "held": held_days[-1] if held_days else None,
            "first_commit": added.get(rel),
        }
        entry: dict[str, object] = {
            "description": fm.get("description", "").strip("\"'"),
            "source": fm.get("source"),
            "anchors": {k: v for k, v in anchors.items() if as_date(v)},
            "weight": source_weight(rel, fm),
        }
        if counts.get(stem):
            entry["outcomes"] = counts[stem]
        if stem in superseded and not indexed:
            entry["history"] = superseded[stem]
        else:
            v = validity(rel, fm, [anchors["confirmed"], anchors["first_commit"]], held_days, today)
            if v:
                entry.update(score=round(v[0], 3), level=v[1], age_days=v[2])
        entries[rel] = entry
    return entries


def refresh(roots: Roots) -> dict[str, object]:
    store, state, today = roots.store, str(roots.state), datetime.date.today()
    data: dict[str, object] = {
        "generated": today.isoformat(),
        "store": store,
        "rule": "source weight ("
        + ", ".join(f"{k or 'unset'} {v}" for k, v in SOURCE_BASE.items())
        + f"; unset in a repo dir's {' or '.join(CODE_TYPES)} {UNSET_CODE_BASE}) minus 0.2 per {DECAY_DAYS} days since"
        f" the anchor (latest of confirmed and first commit, moved to each held day; after more than {DECAY_DAYS} days"
        f" of silence a held day moves it {HELD_AFTER_SILENCE_DAYS} days only)",
        "levels": {name: floor for floor, name in LEVELS},
        "memories": score_store(store, state, today),
    }
    roots.state.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=state, prefix=".memory-validity.")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, os.path.join(state, SCORES_FILE))
    return data


def load(roots: Roots, fresh: bool = True) -> dict[str, object]:
    """The stored scores; rescored first when the file is missing, from an earlier day, or of another store."""
    path = roots.state / SCORES_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    stale = not data or data.get("generated") != datetime.date.today().isoformat() or data.get("store") != roots.store
    if fresh and stale:
        data = refresh(roots)
    return data or {}


def entry_of(path: str, data: dict[str, object]) -> tuple[str, dict[str, object] | None]:
    store = str(data["store"])
    absolute = os.path.realpath(path if os.path.isabs(path) else os.path.join(store, path))
    rel = os.path.relpath(absolute, store)
    memories = data["memories"]
    return rel, memories.get(rel) if isinstance(memories, dict) else None


def refresh_summary(roots: Roots) -> str:
    data = refresh(roots)
    tally: dict[str, int] = {}
    memories = data["memories"]
    for entry in memories.values() if isinstance(memories, dict) else []:
        key = "history" if "history" in entry else entry.get("level", "undated")
        tally[key] = tally.get(key, 0) + 1
    return f"{roots.state / SCORES_FILE}: {', '.join(f'{k} {v}' for k, v in sorted(tally.items()))}"


def levels(roots: Roots, paths: list[str]) -> str:
    data = load(roots)
    lines = []
    for path in paths:
        rel, entry = entry_of(path, data)
        if entry is None:
            lines.append(f"{rel}: not a memory in the store")
        elif "history" in entry:
            lines.append(f"{rel}: history, superseded by {entry['history']}")
        elif "level" not in entry:
            lines.append(f"{rel}: undated")
        else:
            source = entry["source"] or "unset"
            lines.append(f"{rel}: {entry['level']} {entry['score']:.2f} ({entry['age_days']} days, source {source})")
    return "\n".join(lines)


def _append(roots: Roots, name: str, fields: list[str]) -> None:
    roots.state.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    with (roots.state / name).open("a", encoding="utf-8") as handle:
        handle.write("\t".join([datetime.datetime.now().astimezone().isoformat(timespec="seconds"), *fields]) + "\n")


def read_note(roots: Roots, session: str, path: str) -> str | None:
    """memory-outcome --hook: log a Read of a memory (not an index, not personal) and name a history, uncertain or
    stale one; None when there is nothing to say."""
    rel = os.path.relpath(os.path.realpath(path), roots.store)
    if rel.startswith("..") or not rel.endswith(".md") or os.path.basename(rel) == "MEMORY.md" or _personal(rel):
        return None
    _append(roots, READS_LOG, ["read", rel, session[:8]])
    _, entry = entry_of(path, load(roots))
    if not entry:
        return None
    if "history" in entry:
        note = f"superseded by {entry['history']}: history, never act on it"
    elif entry.get("level") in ("uncertain", "stale"):
        note = (
            f"{entry['level']} ({entry['score']:.2f}, scored as {entry['age_days']} days old): check that it still "
            "holds before acting on it"
        )
    else:
        return None
    return f"Memory {rel} is {note}."


def reads(roots: Roots, session: str) -> str:
    seen: list[str] = []
    path = roots.state / READS_LOG
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 4 and parts[3] == session and parts[2] not in seen:
                seen.append(parts[2])
    recall = roots.state / LOG_NAME
    if recall.exists():
        for line in recall.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or event.get("session") != session:
                continue
            if event.get("op") == "open":
                files = [event.get("file")]
            elif event.get("op") == "dump":
                files = event.get("files") or []
            else:
                continue
            for rel in files:
                entry = f"{rel} — {event.get('purpose', 'recall')}, because: {event.get('because', '')}"
                seen = [s for s in seen if s != rel]
                if entry not in seen:
                    seen.append(entry)
    return "\n".join(seen) if seen else f"no store reads logged for session {session}"


def session_memories(roots: Roots, session: str) -> set[str]:
    """The store memories this session recalled (opened to recall) or read with the Read tool, leaving out a Read of a
    file it opened only to save, curate or review, or dumped."""
    read: set[str] = set()
    path = roots.state / READS_LOG
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 4 and parts[3] == session:
                read.add(parts[2])
    recalled: set[str] = set()
    handled: set[str] = set()
    for event in log_events(roots):
        if event.get("session") != session:
            continue
        if event.get("op") == "open":
            (recalled if event.get("purpose", "recall") == "recall" else handled).add(str(event.get("file")))
        elif event.get("op") == "dump" and isinstance(files := event.get("files"), list):
            handled.update(map(str, files))
    return recalled | (read - handled)


def accept(roots: Roots, session: str, outcome: str, paths: list[str]) -> tuple[list[str], list[str]]:
    """The memories among `paths` that the session read or recalled, as store paths, and a line for each left out."""
    if outcome not in OUTCOMES:
        raise OutcomeError(f"outcome must be one of {', '.join(OUTCOMES)}")
    session = session[:8]
    if not session:
        raise OutcomeError("no session id: pass <session8>, or run inside Claude Code")
    lines: list[str] = []
    accepted: list[str] = []
    seen = session_memories(roots, session)
    store = os.path.realpath(roots.store)
    for given in paths:
        rel = (
            given
            if given.startswith("personal:")
            else os.path.relpath(os.path.realpath(os.path.join(store, given)), store)
        )
        path = os.path.join(store, rel)
        if rel.startswith("personal:") or _personal(rel):
            lines.append(f"skipped {given}: personal memories are not scored, so their outcomes are not recorded")
        elif not is_memory_file(os.path.dirname(path), os.path.basename(rel), store) or not os.path.isfile(path):
            lines.append(f"skipped {given}: not a memory file in the store (use the path `reads` prints)")
        elif rel not in seen:
            lines.append(f"skipped {given}: session {session} did not read or recall it, so it has no outcome to judge")
        else:
            accepted.append(rel)
    return lines, accepted


def record(roots: Roots, session: str, outcome: str, rels: list[str]) -> str:
    """Log the outcome for memories `accept` let through; the caller rescores."""
    for rel in rels:
        _append(roots, OUTCOMES_LOG, [outcome, rel, session[:8]])
    return f"recorded {outcome} for {len(rels)} memories"


def quality(roots: Roots, file: str) -> str:
    """Truthness and validity of a memory as `index` names it, for the note that brings it back, on one line: what backs
    it and how its recalls went since its last change, then its level, score and age in days (or history). When one of
    them is weak, a `⚠` line follows that names the state of that knowledge, not what to do: the recall skill says what
    each level asks for. A personal memory is not scored; its truthness comes from its frontmatter alone."""
    if file.startswith("personal:"):
        fm, _ = parse(os.path.join(roots.personal, file[len("personal:") :]))
        source = (fm or {}).get("source")
        lines = [f"Truthness: {source or 'unset'} · Validity: not scored (personal)"]
        if source == "inference":
            lines.append(WEAK_TRUTH.format(why="it was inferred, not measured or decided by the user"))
        return "\n".join(lines)
    _, entry = entry_of(file, load(roots))
    if entry is None and os.path.isfile(os.path.join(roots.store, file)):
        _, entry = entry_of(file, refresh(roots))  # added after today's scores were written
    if entry is None:
        return "Truthness: unknown · Validity: not scored"
    raw = entry.get("outcomes")
    outcomes: dict[str, int] = raw if isinstance(raw, dict) else {}
    tally = ", ".join(f"{name} {outcomes.get(name, 0)}" for name in OUTCOMES)
    truthness = f"Truthness: {entry.get('source') or 'unset'}; {tally}"
    if "history" in entry:
        history = entry["history"]
        return f"{truthness} · Validity: history, superseded by {history}\n⚠ History: {history} replaced it."
    if "level" not in entry:
        lines = [f"{truthness} · Validity: undated"]
    else:
        lines = [f"{truthness} · Validity: {entry['level']} {entry['score']:.2f}, {entry['age_days']} d"]
        if entry["level"] in ("uncertain", "stale"):
            lines.append(
                f"⚠ {str(entry['level']).capitalize()}: scored as {entry['age_days']} days old; a confirmation, or a"
                f" use within {DECAY_DAYS} days of the previous evidence, resets the age; a use after a longer silence"
                f" takes {HELD_AFTER_SILENCE_DAYS} days off only."
            )
    reasons = []
    if entry.get("source") == "inference":
        reasons.append("it was inferred, not measured or decided by the user")
    if outcomes.get("misled"):
        reasons.append(f"it misled {outcomes['misled']} time(s) since its last change")
    if reasons:
        lines.append(WEAK_TRUTH.format(why=" and ".join(reasons)))
    return "\n".join(lines)
