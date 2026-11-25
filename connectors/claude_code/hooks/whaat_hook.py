"""What every whaat hook shares: where the server is, who calls it, and one HTTP call that never fails a tool call.

Stdlib only, so a hook starts fast under any Python. Settings are read as whaat's config reads them: the env var,
else the same key in the `env` block of the Claude config's settings.json (CLAUDE_CONFIG_DIR, else ~/.claude).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request

LIVE_INSTANCE = "live"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 1111
OTHER_INSTANCE_PORT = 1112
TIMEOUT_SECONDS = 2.0
PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(PLUGIN, "scripts", "whaat")
# the server project beside this plugin; run without bash, which a Windows hook may not have
SERVER = os.path.normpath(os.path.join(PLUGIN, "..", "..", "server"))
# on Windows a drive path (C:\repos\x, C:/repos/x) is a local folder; elsewhere x:/path is a one-letter ssh host
DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
WINDOWS = os.name == "nt"


def _settings_env() -> dict[str, str]:
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    try:
        env = json.load(open(os.path.join(os.path.expanduser(config), "settings.json"), encoding="utf-8")).get("env")
    except (OSError, ValueError, AttributeError):
        return {}
    return {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {}


def lookup(name: str) -> str | None:
    return os.environ.get(name) or _settings_env().get(name)


def base_url() -> str:
    instance = lookup("WHAAT_INSTANCE") or LIVE_INSTANCE
    port = lookup("WHAAT_PORT") or (DEFAULT_PORT if instance == LIVE_INSTANCE else OTHER_INSTANCE_PORT)
    return f"http://{lookup('WHAAT_HOST') or DEFAULT_HOST}:{port}"


def call(
    path: str, payload: dict[str, object] | None = None, refused: dict[str, object] | None = None
) -> dict[str, object] | None:
    """POST payload (GET without one) with this identity's token; None when there is no token, no server or an error,
    so a hook that cannot ask says nothing rather than blocking the call."""
    token = lookup("WHAAT_TOKEN")
    if not token:
        return None
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base_url() + path,
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            result = json.load(response)
    except urllib.error.HTTPError:
        return refused
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return result if isinstance(result, dict) else None


def _git(directory, *args):
    try:
        result = subprocess.run(["git", "-C", directory, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _remote_path(url, base, depth=0):
    if not url or depth > 3:
        return None
    if url.startswith("file://"):
        url = url[len("file://"):]
    if url.startswith(("/", "~", ".")) or (WINDOWS and DRIVE_PATH.match(url)):
        local = os.path.normpath(os.path.join(base, os.path.expanduser(url)))
        return _remote_path(_git(local, "remote", "get-url", "origin"), local, depth + 1) if os.path.isdir(local) else None
    if "://" in url:
        rest = url.split("://", 1)[1]
        path = rest.split("/", 1)[1] if "/" in rest else ""
    elif ":" in url:
        path = url.split(":", 1)[1]
    else:
        return None
    path = path.strip("/")
    return path[:-4] if path.endswith(".git") else path


def repo_key(start):
    """(project, repo) of the repo holding start, as memory-where resolves it: the origin remote's group/repo, a
    local-path origin followed to its own origin, local/<dirname> without a remote; None outside git."""
    top = _git(start, "rev-parse", "--show-toplevel")
    if not top:
        return None
    segments = [s for s in (_remote_path(_git(top, "remote", "get-url", "origin"), top) or "").split("/") if s]
    if len(segments) >= 2:
        return [segments[0], segments[-1]]
    return ["local", os.path.basename(top)]


def ensure_server():
    """Start this instance's whaat through the CLI when it does not run; True when the CLI says it runs."""
    try:
        result = subprocess.run(
            ["uv", "run", "--quiet", "--project", SERVER, "whaat", "ensure"], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0
