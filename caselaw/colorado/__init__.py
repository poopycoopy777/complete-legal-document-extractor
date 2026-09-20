"""Live checks against official Colorado legal sources.

Cloned from the legal-citation-verification-system project and made
standalone. These functions reach out over the network; everything else in
`caselaw` is local and deterministic.
"""

from .sources import (
    verify_colorado_case_search,
    verify_colorado_court_of_appeals,
    verify_colorado_supreme_court,
    verify_crs,
    verify_session_law,
)
from .types import ExtractedCitation, ProvisionResult

__all__ = [
    "ExtractedCitation",
    "ProvisionResult",
    "verify_colorado_case_search",
    "verify_colorado_court_of_appeals",
    "verify_colorado_supreme_court",
    "verify_crs",
    "verify_session_law",
]
