import os
from pathlib import Path


def write_private(path: Path, text: str) -> None:
    """Write a file with mode 0600 (on Windows the profile folder's access rules keep it private, since there chmod
    only sets the read-only flag). The mode os.open gives holds only for a new file, so it is set again, by path:
    os.fchmod is missing on Windows before Python 3.13."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(path, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
