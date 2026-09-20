"""Where fetched Colorado sources are preserved.

Replaces the original project's settings object. The cloned source functions
reference `settings.colorado_opinions_dir` and `settings.session_laws_dir`, so
those names are kept.

These directories hold copies of documents served by Colorado courts and the
legislature, written under their own SHA-256. They are evidence of what a
source said at a moment in time, so they are never modified in place: a file
whose hash already matches is left exactly as it is.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _path(env_var: str, default: str) -> str:
    override = os.environ.get(env_var)
    return override if override else str(_ROOT / default)


@dataclass(frozen=True)
class Settings:
    colorado_opinions_dir: str
    session_laws_dir: str
    # The original used 2s for search endpoints and 20s for the statute
    # download, which are the page-weight difference. Kept.
    search_timeout: float = 2.0
    document_timeout: float = 20.0


settings = Settings(
    colorado_opinions_dir=_path(
        "COLORADO_OPINIONS_DIR", "data/colorado_opinions"
    ),
    session_laws_dir=_path("COLORADO_SESSION_LAWS_DIR", "data/session_laws"),
)
