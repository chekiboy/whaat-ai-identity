import json
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2] / "connectors" / "claude_code"


def test_every_hook_runs_its_script_through_uv_without_the_session_repo_s_python_pins_or_uv_settings() -> None:
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    commands = [hook for groups in hooks.values() for group in groups for hook in group["hooks"]]

    assert commands
    for hook in commands:
        assert (hook["command"], hook["args"][:5]) == (
            "uv",
            ["run", "--no-project", "--no-config", "--quiet", "python"],
        )
        script = hook["args"][5].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
        assert Path(script).is_file(), script
