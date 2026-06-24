"""Fail if requirements.txt has drifted from poetry.lock.

``requirements.txt`` is a *generated* artifact — it's what Hugging Face Spaces
installs (`pip install -r requirements.txt`), exported from ``poetry.lock`` via
``poetry export --without-hashes --extras web -o requirements.txt``. Poetry/CI use
the lock; HF uses requirements.txt. If they disagree, the deployed app runs
different (untested) dependency versions than CI exercised.

This check compares, per package, the pinned version in requirements.txt against
poetry.lock. It is intentionally *semantic* (version equality), not a byte diff of
a fresh export, so it doesn't false-positive on marker-formatting differences
between poetry/plugin versions — it only flags real version drift or a package
pinned in requirements.txt that isn't in the lock.

Regenerate with: ``poetry export --without-hashes --extras web -o requirements.txt``
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "poetry.lock"
REQUIREMENTS = ROOT / "requirements.txt"

_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9._-]+)==([^\s;]+)")


def _normalize(name: str) -> str:
    """PEP 503 name normalization (case-insensitive, -/_/. collapse to -)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def main() -> int:
    lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    lock_versions = {_normalize(pkg["name"]): pkg["version"] for pkg in lock["package"]}

    mismatches: list[str] = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        match = _REQ_LINE.match(raw)
        if match is None:
            continue
        name, version = _normalize(match.group(1)), match.group(2)
        locked = lock_versions.get(name)
        if locked is None:
            mismatches.append(f"{name}=={version} is in requirements.txt but not in poetry.lock")
        elif locked != version:
            mismatches.append(f"{name}: requirements.txt=={version} but poetry.lock=={locked}")

    if mismatches:
        print("requirements.txt is OUT OF SYNC with poetry.lock:")
        for line in mismatches:
            print(f"  - {line}")
        print(
            "\nregenerate it from the lock:\n"
            "  poetry export --without-hashes --extras web -o requirements.txt"
        )
        return 1

    print("requirements.txt is in sync with poetry.lock.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
