"""Probe the live extractor API with a real file, so the API contract is seen.

Writes the response to a JSON file and prints the fields the app depends on:
the hashed bytes, the page table, the highlight table, and the extraction
counts. Read-only against storage: POST /api/documents writes its own copy
under storage/, which is the API's normal behaviour.

Usage:
    python scripts/probe_upload.py <file> --out <response.json>
"""

from __future__ import annotations

import argparse
import json
import urllib.request
import uuid
from pathlib import Path

API = "http://127.0.0.1:8010"


def multipart(path: Path, field: str = "file") -> tuple[bytes, str]:
    boundary = "----bench" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return head + path.read_bytes() + tail, boundary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    body, boundary = multipart(args.path)
    request = urllib.request.Request(
        f"{API}/api/documents",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=1800) as response:
        payload = json.load(response)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

    pages = payload.get("pages") or []
    extraction = payload.get("extraction") or {}
    print(f"name={payload.get('name')} kind={payload.get('kind')} "
          f"sha256={payload.get('sha256')}")
    print(f"textSource={payload.get('textSource')} pageCount={payload.get('pageCount')} "
          f"pages_table={len(pages)} highlights={len(payload.get('highlights') or [])}")
    print(f"ocr={json.dumps(payload.get('ocr'))}")
    print(f"warning={(payload.get('warning') or '')[:160]}")
    print(f"notes={payload.get('notes')}")
    print(f"stats={json.dumps(extraction.get('stats'))}")
    unmapped = 0
    for h in payload.get("highlights") or []:
        if h.get("page") is None:
            unmapped += 1
    print(f"highlights_without_page={unmapped}")
    if extraction.get("groups") and not pages:
        print("CONTRACT: groups carry spans but the response has no page table")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
