import datetime
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TOKEN, write
from whaat.memory.validity import OUTCOMES_LOG, anchor_day, recall_outcomes, source_weight

ADMIN = {"Authorization": f"Bearer {TOKEN}"}
TODAY = datetime.date.today()


@pytest.fixture
def isolated_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = write(tmp_path / "gitconfig", "[user]\n\tname = Test\n\temail = test@example.com\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def trial(client: TestClient, isolated_git: None) -> dict[str, str]:
    response = client.post("/api/v1/identities", json={"id": "trial"}, headers=ADMIN)
    return {"Authorization": f"Bearer {response.json()['token']}"}


def memory_file(name: str, **fields: str) -> str:
    head = "".join(f"{key}: {value}\n" for key, value in fields.items())
    return f"---\nname: {name}\ndescription: When {name}\n{head}---\nBody.\n"


@pytest.fixture
def folder(client: TestClient, trial: dict[str, str], settings: Any) -> Path:
    root = settings.state_dir / "identities" / "trial"
    client.post(
        "/api/v1/memory/memories",
        json={
            "path": "acme/shop/feedback_new.md",
            "content": memory_file("feedback_new", source="measured"),
            "trigger": "When new",
        },
        headers=trial,
    )
    memory = root / "memory"
    write(
        memory / "acme/shop/feedback_old.md", memory_file("feedback_old", source="inference", confirmed="'2026-01-01'")
    )
    write(memory / "acme/shop/feedback_gone.md", memory_file("feedback_gone", confirmed="2026-10-01"))
    write(
        memory / "acme/shop/feedback_now.md",
        memory_file("feedback_now", confirmed="2026-10-01", supersedes="feedback_gone"),
    )
    with (memory / "acme/shop/MEMORY.md").open("a") as handle:
        handle.write("- feedback_old.md — When old\n- feedback_now.md — When now\n")
    write(memory / "personal/user_x.md", memory_file("user_x", confirmed="2020-01-01"))
    return root


def post(client: TestClient, auth: dict[str, str], endpoint: str, **body: Any) -> Any:
    return client.post(f"/api/v1/memory/{endpoint}", json=body, headers=auth)


def expected(base: float, day: datetime.date) -> float:
    return round(max(0.0, base - 0.2 / 30 * (TODAY - day).days), 3)


def test_refresh_scores_from_source_and_latest_anchor_and_leaves_personal_out(
    client: TestClient, trial: dict[str, str], folder: Path
) -> None:
    unset = memory_file("project_unset", type="project", confirmed=str(TODAY - datetime.timedelta(days=30)))
    write(folder / "memory/acme/shop/project_unset.md", unset)
    summary = post(client, trial, "validity/refresh").json()["text"]
    data = json.loads((folder / "state/memory-validity.json").read_text())

    assert summary.startswith(f"{folder / 'state/memory-validity.json'}: ")
    assert data["store"] == str((folder / "memory").resolve())
    assert sorted(data["memories"]) == [
        "acme/shop/feedback_gone.md",
        "acme/shop/feedback_new.md",
        "acme/shop/feedback_now.md",
        "acme/shop/feedback_old.md",
        "acme/shop/project_unset.md",
    ]
    new, old = data["memories"]["acme/shop/feedback_new.md"], data["memories"]["acme/shop/feedback_old.md"]
    assert (new["anchors"], new["score"], new["level"]) == ({"first_commit": TODAY.isoformat()}, 1.0, "certain")
    assert old["anchors"] == {"confirmed": "2026-01-01"}
    assert old["score"] == expected(0.75, datetime.date(2026, 1, 1))
    assert data["memories"]["acme/shop/feedback_gone.md"]["history"] == "acme/shop/feedback_now.md"
    assert data["memories"]["acme/shop/project_unset.md"]["score"] == expected(0.8, TODAY - datetime.timedelta(days=30))
    assert (data["memories"]["acme/shop/project_unset.md"]["weight"], old["weight"], new["weight"]) == (0.8, 0.75, 1.0)


def test_a_store_file_a_personal_memory_supersedes_is_history_and_not_scored(
    client: TestClient, trial: dict[str, str], folder: Path
) -> None:
    memory = folder / "memory"
    write(memory / "acme/shop/reference_old_pointer.md", memory_file("reference_old_pointer", confirmed="2026-10-01"))
    write(
        memory / "personal/reference_new_pointer.md",
        memory_file("reference_new_pointer", supersedes="reference_old_pointer"),
    )

    post(client, trial, "validity/refresh")
    entry = json.loads((folder / "state/memory-validity.json").read_text())["memories"][
        "acme/shop/reference_old_pointer.md"
    ]

    assert entry.get("history") == "personal:reference_new_pointer"
    assert "score" not in entry


def test_a_read_is_logged_and_a_weak_memory_named_but_not_a_personal_one_or_an_index(
    client: TestClient, trial: dict[str, str], folder: Path
) -> None:
    memory = folder / "memory"
    gone = post(client, trial, "outcome/read", session="abcd1234ef", path=str(memory / "acme/shop/feedback_gone.md"))
    fresh = post(client, trial, "outcome/read", session="abcd1234ef", path=str(memory / "acme/shop/feedback_new.md"))
    personal = post(client, trial, "outcome/read", session="abcd1234ef", path=str(memory / "personal/user_x.md"))
    index = post(client, trial, "outcome/read", session="abcd1234ef", path=str(memory / "acme/shop/MEMORY.md"))

    assert gone.json()["text"] == (
        "Memory acme/shop/feedback_gone.md is superseded by acme/shop/feedback_now.md: history, never act on it."
    )
    assert fresh.json()["text"] is personal.json()["text"] is index.json()["text"] is None
    logged = [line.split("\t") for line in (folder / "state/memory-reads.log").read_text().splitlines()]
    assert [fields[1:] for fields in logged] == [
        ["read", "acme/shop/feedback_gone.md", "abcd1234"],
        ["read", "acme/shop/feedback_new.md", "abcd1234"],
    ]
    assert all(datetime.datetime.fromisoformat(fields[0]).date() == TODAY for fields in logged)
    assert post(client, trial, "outcome/reads", session="abcd1234").json()["text"] == (
        "acme/shop/feedback_gone.md\nacme/shop/feedback_new.md"
    )
    assert post(client, trial, "outcome/reads", session="other000").json()["text"] == (
        "no store reads logged for session other000"
    )


def test_record_keeps_memories_the_session_read_or_recalled_and_a_held_one_is_rescored_at_once(
    client: TestClient, trial: dict[str, str], folder: Path
) -> None:
    memory = folder / "memory"
    confirmed = TODAY - datetime.timedelta(days=60)
    write(
        memory / "acme/shop/feedback_aged.md",
        memory_file("feedback_aged", source="inference", confirmed=str(confirmed)),
    )
    post(client, trial, "outcome/read", session="abcd1234", path=str(memory / "acme/shop/feedback_aged.md"))
    recorded = post(
        client,
        trial,
        "outcome/record",
        session="abcd1234ef",
        outcome="held",
        paths=["./acme/shop/feedback_aged.md", "acme/shop/feedback_new.md", "personal/user_x.md", "personal:user_x.md"],
    ).json()["text"]
    data = json.loads((folder / "state/memory-validity.json").read_text())

    assert recorded.splitlines() == [
        "skipped acme/shop/feedback_new.md: session abcd1234 did not read or recall it, so it has no outcome to judge",
        "skipped personal/user_x.md: personal memories are not scored, so their outcomes are not recorded",
        "skipped personal:user_x.md: personal memories are not scored, so their outcomes are not recorded",
        "recorded held for 1 memories",
    ]
    aged = data["memories"]["acme/shop/feedback_aged.md"]
    assert aged["anchors"]["held"] == TODAY.isoformat()
    assert aged["score"] == expected(0.75, confirmed + datetime.timedelta(days=7))


def test_an_open_to_recall_counts_for_record_but_an_open_to_save_does_not_even_with_a_read_after_it(
    client: TestClient, trial: dict[str, str], folder: Path
) -> None:
    memory = folder / "memory"

    def open_(file: str, purpose: str) -> None:
        body = {"session": "abcd1234", "file": file, "because": "the task matches", "purpose": purpose}
        client.post("/api/v1/memory/recall/open", json=body, headers=trial)

    open_("acme/shop/feedback_old.md", "recall")
    open_("acme/shop/MEMORY.md", "recall")
    open_("acme/shop/feedback_new.md", "save")
    post(client, trial, "outcome/read", session="abcd1234", path=str(memory / "acme/shop/feedback_new.md"))
    dump = {"session": "abcd1234", "dir": "acme/shop", "because": "curating the shop", "purpose": "curate"}
    client.post("/api/v1/memory/recall/dump", json=dump, headers=trial)
    post(client, trial, "outcome/read", session="abcd1234", path=str(memory / "acme/shop/feedback_now.md"))
    paths = [
        "acme/shop/feedback_old.md",
        "acme/shop/feedback_new.md",
        "acme/shop/feedback_now.md",
        "acme/shop/MEMORY.md",
        "./personal/user_x.md",
    ]

    recorded = post(client, trial, "outcome/record", session="abcd1234", outcome="held", paths=paths)

    assert recorded.json()["text"].splitlines() == [
        "skipped acme/shop/feedback_new.md: session abcd1234 did not read or recall it, so it has no outcome to judge",
        "skipped acme/shop/feedback_now.md: session abcd1234 did not read or recall it, so it has no outcome to judge",
        "skipped acme/shop/MEMORY.md: not a memory file in the store (use the path `reads` prints)",
        "skipped ./personal/user_x.md: personal memories are not scored, so their outcomes are not recorded",
        "recorded held for 1 memories",
    ]


def test_a_held_codebase_fact_without_a_source_gets_measured_and_confirmed_today_in_a_commit(
    client: TestClient, trial: dict[str, str], folder: Path
) -> None:
    memory = folder / "memory"
    files = {
        "acme/shop/project_db.md": memory_file("project_db", type="project", confirmed="2026-01-01"),
        "acme/shop/feedback_style.md": memory_file("feedback_style", type="feedback"),
        "acme/shop/reference_run.md": memory_file("reference_run", type="reference", source="user-decision"),
        "acme/shop/project_cache.md": memory_file("project_cache", type="project"),
    }
    for rel, text in files.items():
        write(memory / rel, text)
        post(client, trial, "outcome/read", session="abcd1234", path=str(memory / rel))

    post(client, trial, "outcome/record", session="abcd1234", outcome="misled", paths=["acme/shop/project_cache.md"])
    recorded = post(client, trial, "outcome/record", session="abcd1234", outcome="held", paths=list(files)).json()

    db = (memory / "acme/shop/project_db.md").read_text()
    assert recorded["text"].splitlines()[-1] == "source measured, confirmed today: acme/shop/project_db.md"
    assert "source: measured\n" in db and f"confirmed: {TODAY}\n" in db and "2026-01-01" not in db
    assert (memory / "acme/shop/feedback_style.md").read_text() == files["acme/shop/feedback_style.md"]
    assert (memory / "acme/shop/reference_run.md").read_text() == files["acme/shop/reference_run.md"]
    assert (memory / "acme/shop/project_cache.md").read_text() == files["acme/shop/project_cache.md"]
    assert "acme/shop/project_cache.md" not in recorded["text"]
    log = subprocess.run(["git", "log", "-1", "--format=%s", "--name-only"], cwd=folder, capture_output=True, text=True)
    assert log.stdout.split() == [
        "memory:",
        "source",
        "measured",
        "on",
        "acme/shop/project_db.md",
        "memory/acme/shop/project_db.md",
    ]
    data = json.loads((folder / "state/memory-validity.json").read_text())
    assert data["memories"]["acme/shop/project_db.md"]["score"] == 1.0
    assert data["memories"]["acme/shop/project_db.md"]["outcomes"] == {"held": 1}
    assert data["memories"]["acme/shop/project_cache.md"]["outcomes"] == {"misled": 1, "held": 1}


def test_any_recorded_outcome_rescores_at_once_and_counts_each_session_once(
    client: TestClient, trial: dict[str, str], folder: Path
) -> None:
    post(client, trial, "validity/refresh")
    memory = folder / "memory"
    for session in ("abcd1234", "abcd1234", "efgh5678"):
        post(client, trial, "outcome/read", session=session, path=str(memory / "acme/shop/feedback_old.md"))
        post(client, trial, "outcome/record", session=session, outcome="misled", paths=["acme/shop/feedback_old.md"])

    data = json.loads((folder / "state/memory-validity.json").read_text())

    assert data["memories"]["acme/shop/feedback_old.md"]["outcomes"] == {"misled": 2}


def day(n: int) -> str:
    return (datetime.date(2026, 1, 1) + datetime.timedelta(days=n)).isoformat()


@pytest.mark.parametrize(
    ("held", "anchor"),
    [
        ([], 0),
        ([day(20)], 20),
        ([day(40)], 7),
        ([day(40), day(46)], 46),
        ([day(40), day(40)], 7),
        ([day(40), day(80)], 14),
        ([day(-5)], 0),
    ],
    ids=[
        "no use",
        "use within 30 days",
        "use after silence",
        "weekly use after silence",
        "same day once",
        "two uses after silence",
        "use before the start",
    ],
)
def test_the_anchor_moves_to_a_use_within_30_days_and_one_week_after_a_longer_silence(
    held: list[str], anchor: int
) -> None:
    assert anchor_day([day(0), None], held) == datetime.date.fromisoformat(day(anchor))


def test_with_no_start_the_first_use_starts_the_anchor() -> None:
    assert anchor_day([None], [day(3), day(9)]) == datetime.date.fromisoformat(day(9))
    assert anchor_day([None], []) is None


@pytest.mark.parametrize(
    ("rel", "fields", "weight"),
    [
        ("acme/shop/project_x.md", {"type": "project"}, 0.8),
        ("acme/shop/reference_x.md", {"type": "reference"}, 0.8),
        ("acme/shop/feedback_x.md", {"type": "feedback"}, 0.9),
        ("acme/project_x.md", {"type": "project"}, 0.9),
        ("reference_x.md", {"type": "reference"}, 0.9),
        ("acme/shop/project_x.md", {"type": "project", "source": "measured"}, 1.0),
    ],
)
def test_an_unset_source_weighs_less_only_for_a_codebases_fact_or_recipe(
    rel: str, fields: dict[str, str], weight: float
) -> None:
    assert source_weight(rel, fields) == weight


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            {"session": "abcd1234", "outcome": "fine", "paths": ["x.md"]},
            "outcome must be one of held, misled, irrelevant",
        ),
        (
            {"session": "", "outcome": "held", "paths": ["x.md"]},
            "no session id: pass <session8>, or run inside Claude Code",
        ),
    ],
)
def test_record_refuses_what_memory_outcome_refuses(
    client: TestClient, trial: dict[str, str], folder: Path, body: dict[str, Any], message: str
) -> None:
    refused = post(client, trial, "outcome/record", **body)

    assert (refused.status_code, refused.json()["detail"]) == (422, message)


def test_level_names_each_memory_as_memory_validity_does(
    client: TestClient, trial: dict[str, str], folder: Path
) -> None:
    text = post(
        client,
        trial,
        "validity/level",
        paths=["acme/shop/feedback_new.md", "acme/shop/feedback_gone.md", "acme/shop/none.md"],
    ).json()["text"]

    assert text.splitlines() == [
        "acme/shop/feedback_new.md: certain 1.00 (0 days, source measured)",
        "acme/shop/feedback_gone.md: history, superseded by acme/shop/feedback_now.md",
        "acme/shop/none.md: not a memory in the store",
    ]


def test_a_returning_memory_carries_its_truthness_and_validity(
    client: TestClient, trial: dict[str, str], folder: Path
) -> None:
    memory = folder / "memory"
    write(
        memory / "acme/shop/feedback_stale.md",
        memory_file("feedback_stale", source="user-decision", confirmed="2025-03-01"),
    )
    with (memory / "acme/shop/MEMORY.md").open("a") as handle:
        handle.write("- feedback_stale.md — When stale\n")
    post(client, trial, "outcome/read", session="abcd1234", path=str(memory / "acme/shop/feedback_stale.md"))
    post(client, trial, "outcome/record", session="abcd1234", outcome="misled", paths=["acme/shop/feedback_stale.md"])
    post(
        client, trial, "outcome/record", session="abcd1234", outcome="irrelevant", paths=["acme/shop/feedback_stale.md"]
    )

    def framed(rel: str, path: Path) -> str:
        body = {"session": "s1", "opened": [{"file": rel, "path": str(path.resolve())}]}
        return client.post("/api/v1/memory/recall/frame", json=body, headers=trial).json()["context"]

    stale = framed("acme/shop/feedback_stale.md", memory / "acme/shop/feedback_stale.md")
    gone = framed("acme/shop/feedback_gone.md", memory / "acme/shop/feedback_gone.md")
    personal = framed("personal:user_x.md", memory / "personal/user_x.md")

    age = (TODAY - datetime.date(2025, 3, 1)).days
    assert stale.splitlines()[:4] == [
        "Memory: acme/shop/feedback_stale.md · Truthness: user-decision; held 0, misled 1, irrelevant 1"
        f" · Validity: stale 0.00, {age} d",
        f"⚠ Stale: scored as {age} days old; a confirmation, or a use within 30 days of the previous evidence, resets"
        " the age; a use after a longer silence takes 7 days off only.",
        "⚠ Weak truthness: it misled 1 time(s) since its last change.",
        "",
    ]
    assert gone.splitlines()[0].endswith(" · Validity: history, superseded by acme/shop/feedback_now.md")
    assert gone.splitlines()[1] == "⚠ History: acme/shop/feedback_now.md replaced it."
    assert personal.splitlines()[:2] == [
        "Memory: personal:user_x.md · Truthness: unset · Validity: not scored (personal)",
        "",
    ]


def test_a_memory_added_after_todays_scores_is_scored_when_it_returns(
    client: TestClient, trial: dict[str, str], folder: Path
) -> None:
    post(client, trial, "validity/refresh")
    memory = folder / "memory"
    write(
        memory / "acme/shop/reference_late.md",
        memory_file("reference_late", source="inference", confirmed="2025-01-15"),
    )
    body = {
        "session": "s1",
        "opened": [{"file": "acme/shop/reference_late.md", "path": str(memory / "acme/shop/reference_late.md")}],
    }

    note = client.post("/api/v1/memory/recall/frame", json=body, headers=trial).json()["context"]

    assert " · Truthness: inference; " in note.splitlines()[0]
    assert " · Validity: stale 0.00, " in note.splitlines()[0]
    assert note.splitlines()[2] == "⚠ Weak truthness: it was inferred, not measured or decided by the user."


def test_a_change_resets_the_outcome_counts_but_keeps_the_days_it_held(tmp_path: Path) -> None:
    write(
        tmp_path / OUTCOMES_LOG,
        "2026-01-15T10:00:00+00:00\theld\tacme/shop/feedback_x.md\ts1\n"
        "2026-02-03T10:00:00+00:00\tmisled\tacme/shop/feedback_x.md\ts2\n",
    )

    held, counts = recall_outcomes(str(tmp_path), {"feedback_x": "2026-02-01T00:00:00+00:00"})

    assert (held, counts) == ({"feedback_x": ["2026-01-15"]}, {"feedback_x": {"misled": 1}})


def test_a_misled_before_the_last_change_does_not_keep_a_held_codebase_fact_from_its_stamp(
    client: TestClient, trial: dict[str, str], folder: Path
) -> None:
    memory = folder / "memory"
    write(folder / "state/memory-outcomes.log", "2020-01-01T10:00:00+00:00\tmisled\tacme/shop/project_fixed.md\told\n")
    body = {
        "path": "acme/shop/project_fixed.md",
        "content": memory_file("project_fixed", type="project"),
        "trigger": "x",
    }
    client.post("/api/v1/memory/memories", json=body, headers=trial)
    post(client, trial, "outcome/read", session="abcd1234", path=str(memory / "acme/shop/project_fixed.md"))

    recorded = post(
        client, trial, "outcome/record", session="abcd1234", outcome="held", paths=["acme/shop/project_fixed.md"]
    )

    assert recorded.json()["text"].splitlines()[-1] == "source measured, confirmed today: acme/shop/project_fixed.md"
