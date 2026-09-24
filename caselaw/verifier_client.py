"""Client for The Verifyer, the standalone verification service.

This application extracts citations. It does not verify them. Verification lives
in a separate read-only service that owns the corpus, the resolution ladder, and
the evidence rules, and this module is the only thing that talks to it.

What that separation buys: absence of a citation from any one source stops being
a conclusion here. The service runs a ladder -- local corpus, then CourtListener,
then the official Colorado source -- and only reports a verdict once the ladder
is exhausted. This app never has to decide what a miss means.

The service is expected at VERIFIER_API_URL (default http://127.0.0.1:8020).
It being down is an outage, never an empty result: a document full of real
citations and a document the verifier could not reach look identical if you
report both as "nothing verified".
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8020"
TIMEOUT_SECONDS = 120


class VerifierUnavailable(RuntimeError):
    """The verification service did not run. Distinct from reaching no conclusion."""


def base_url() -> str:
    return os.environ.get("VERIFIER_API_URL", DEFAULT_URL).rstrip("/")


def _court_id(group: dict[str, Any]) -> str | None:
    """Prefer the resolved court id; fall back to nothing.

    The printed parenthetical ("Colo. App.") is not a court id and must not be
    passed off as one -- a wrong court id produces a court_mismatch, which is a
    finding against the citation rather than against our parsing.
    """
    court = group.get("court")
    return str(court) if court else None


def _case_name(group: dict[str, Any]) -> str:
    explicit = group.get("caseName")
    if explicit:
        return str(explicit)
    plaintiff, defendant = group.get("plaintiff"), group.get("defendant")
    if plaintiff and defendant:
        return f"{plaintiff} v. {defendant}"
    return str(plaintiff or defendant or "")


def to_case_payload(group: dict[str, Any]) -> dict[str, Any] | None:
    """Map an extracted citation group onto the service's case contract."""
    full_group = group if "header" in group else None
    if full_group is not None:
        group = {
            **full_group["header"],
            "groupId": full_group["id"],
            "caseName": full_group.get("caseName") or full_group["header"].get("case_name"),
            "courtText": full_group["header"].get("court_text"),
            "quotes": full_group.get("quotes", []),
        }
    volume, reporter, page = group.get("volume"), group.get("reporter"), group.get("page")
    if not (volume and reporter and page):
        return None
    case_name = _case_name(group)
    if not case_name:
        return None

    payload: dict[str, Any] = {
        "caller_id": str(group.get("groupId") or ""),
        "volume": int(volume),
        "reporter": str(reporter),
        "page": int(page),
        "case_name": case_name,
    }
    if group.get("year"):
        payload["year"] = int(group["year"])
    court = _court_id(group)
    if court:
        payload["court_id"] = court
    if group.get("courtText"):
        payload["court_text"] = str(group["courtText"])
    if group.get("pinPage"):
        payload["pin_page"] = int(group["pinPage"])
    # A brief quotes a case several times at several pages, so quotations go
    # over as a list with each pin cite as printed. Sending only the first would
    # leave every later fabricated quote unchecked.
    quotes = []
    for quote in group.get("quotes") or []:
        text = (quote or {}).get("text") if isinstance(quote, dict) else None
        if not text or not str(text).strip():
            continue
        entry = {"text": str(text)}
        pin = (quote or {}).get("pin_cite")
        if pin:
            entry["pin_cite"] = str(pin)
        quotes.append(entry)
    if quotes:
        payload["quotes"] = quotes
    if group.get("quotedText"):
        payload["quoted_text"] = str(group["quotedText"])
    if group.get("proposition"):
        payload["proposition"] = str(group["proposition"])
    if full_group is not None:
        citations = [full_group["header"], *full_group.get("children", [])]
        ids = {tuple(c["span"]): f"{full_group['id']}:c{i}" for i, c in enumerate(citations)}
        payload["occurrences"] = [{
            "occurrence_id": ids[tuple(c["span"])], "source_span": list(c["span"]),
            "text": c["text"], "pin_cite": c.get("pin_cite"),
            "claimed_opinion_part": c.get("parenthetical"),
        } for c in citations]
        payload["quotes"] = []
        for index, quote in enumerate(full_group.get("quotes", [])):
            entry = {"text": quote["text"], "pin_cite": quote.get("pin_cite")}
            owner = ids.get(tuple(quote.get("citation_span") or ()))
            if owner is not None:
                entry.update(quote_id=f"{full_group['id']}:q{index}",
                             source_span=list(quote["span"]), citation_occurrence_id=owner)
            payload["quotes"].append(entry)
    return payload


def verify_groups(groups: list[dict[str, Any]], *, analyze: bool = False) -> dict[str, Any]:
    """Send extracted groups to the verification service and return its response."""
    cases = [payload for payload in map(to_case_payload, groups) if payload]
    if not cases:
        return {"request_id": "", "results": [], "authorities": [], "counts": {"total": 0}}

    body = json.dumps(
        {"request_id": f"legal-app:{len(cases)}", "cases": cases, "analyze": analyze}
    ).encode()
    request = urllib.request.Request(
        f"{base_url()}/v1/verify",
        data=body,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise VerifierUnavailable(
            f"Verification service returned HTTP {exc.code}: {detail}"
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VerifierUnavailable(
            f"Verification service at {base_url()} could not be reached "
            f"({type(exc).__name__})."
        ) from None


def capabilities() -> dict[str, Any]:
    try:
        with urllib.request.urlopen(f"{base_url()}/v1/capabilities", timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VerifierUnavailable(
            f"Verification service at {base_url()} could not be reached "
            f"({type(exc).__name__})."
        ) from None


def to_legacy_verified(result: dict[str, Any]) -> dict[str, Any] | None:
    """Project a confirmed identity onto the shape the existing UI expects.

    Only a passing identity becomes a legacy entry. Everything else -- flagged,
    unresolved, unavailable -- is carried in the full result instead, so the old
    positive-only contract keeps working without hiding the new verdicts.
    """
    identity = result.get("identity") or {}
    if identity.get("status") != "pass":
        return None
    return {
        "groupId": result.get("caller_id"),
        "status": "citation_verified",
        "clusterId": identity.get("cluster_id"),
        "checks": {
            "reporterCitation": True,
            "caseName": True,
            "year": True,
            "court": True,
        },
        "source": (identity.get("searched") or ["local_corpus"])[-1],
    }
