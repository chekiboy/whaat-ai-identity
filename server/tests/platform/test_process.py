import pytest

from whaat.platform import process


@pytest.mark.parametrize(
    ("system", "expected"),
    [
        ("windows", {"creationflags": 0x00000008 | 0x00000200}),
        ("linux", {"start_new_session": True}),
        ("macos", {"start_new_session": True}),
    ],
)
def test_a_started_process_is_detached_the_way_its_system_allows(
    monkeypatch: pytest.MonkeyPatch, system: str, expected: dict[str, object]
) -> None:
    monkeypatch.setattr(process, "system", lambda: system)

    assert process.detach_options() == expected
