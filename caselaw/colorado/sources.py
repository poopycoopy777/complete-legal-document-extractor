"""Official Colorado legal sources, checked live over the network.

This standalone copy started from the legal-citation-verification-system
implementation: its types live in `.types`, its paths come from `.config`,
and nothing here imports from that repository.  Its search adapter is kept
current with the response contract served by the public Colorado site.

Unlike the rest of this package, these functions make outbound requests to
Colorado court and legislature servers. Every document fetched is written to
disk under its own SHA-256 and re-read to confirm the hash before it is
trusted, so a verified citation can be traced back to the exact bytes that
were served.
"""

import hashlib
import re
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import httpx
import pymupdf as fitz
from bs4 import BeautifulSoup

from .config import settings
from .types import ExtractedCitation, ProvisionResult

CRS_RELEASES = (
    (date(2025, 6, 5), 2024),
    (date(2025, 9, 16), 2025),
    (date(2026, 8, 20), 2026),
)
CRS_BASE_URL = "https://olls.info/crs"
SESSION_LAWS_URL = "https://leg.colorado.gov/laws/session-laws"
COLORADO_SUPREME_COURT_OPINIONS_URL = "https://www.coloradojudicial.gov/supreme-court/opinions"
COLORADO_COURT_OF_APPEALS_ANNOUNCEMENTS_URL = (
    "https://www.coloradojudicial.gov/court-appeals/court-appeals-case-announcements"
)
COLORADO_CASE_LAW_SEARCH_URL = "https://research.coloradojudicial.gov"

# The public Colorado search UI sends this header on every search request.
# Without it the same anonymous endpoint silently uses a much smaller result
# set (for example, 106 instead of 1,470 results for ``576 P.3d 225``) and can
# omit the exact case.  The server currently treats the numeric value as an
# opaque public-client seed; presence selects the web application's search
# mode.  No account, cookie, or credential is involved.
COLORADO_CASE_LAW_SEARCH_HEADERS = {"X-webapp-seed": "1"}

_COLORADO_SEARCH_CACHE: dict[str, ProvisionResult] = {}


def _section_text(document: str, section: str) -> str | None:
    text = " ".join(BeautifulSoup(document, "html.parser").get_text(" ").replace("\xa0", " ").replace("\ufffd", " ").split())
    matches = list(re.finditer(rf"(?<![\w-]){re.escape(section)}\.\s", text))
    if not matches:
        return None
    candidates: list[str] = []
    for heading in matches:
        next_heading = re.search(r"(?<![\w-])\d{1,2}-\d{1,3}-\d+[A-Za-z]?\.\s", text[heading.end() :])
        end = heading.end() + next_heading.start() if next_heading else len(text)
        candidates.append(text[heading.start() : end].strip())
    return max(candidates, key=len)


def _subdivision_text(section_text: str, subsection: str) -> str | None:
    scope = section_text
    for label in re.findall(r"\(([0-9A-Za-z.]+)\)", subsection):
        marker = f"({label})"
        match = re.search(rf"(?:^|\s){re.escape(marker)}(?:\s|\.|,|;|$)", scope)
        if match is None:
            return None
        if re.fullmatch(r"\d+(?:\.\d+)?", label):
            sibling_pattern = r"\(\d+(?:\.\d+)?\)"
        elif label.isupper() and all(character in "IVXLC" for character in label):
            sibling_pattern = r"\([IVXLC]+\)"
        elif label.isupper():
            sibling_pattern = r"\([A-Z]+\)"
        else:
            sibling_pattern = r"\([a-z]+\)"
        remainder = scope[match.end() :]
        sibling = re.search(rf"(?:^|\s){sibling_pattern}(?:\s|\.|,|;|$)", remainder)
        end = match.end() + sibling.start() if sibling else len(scope)
        scope = scope[match.start() : end].strip()
    return scope


async def verify_crs(
    citation: ExtractedCitation,
    client: httpx.AsyncClient | None = None,
    as_of_date: str | None = None,
) -> ProvisionResult:
    crs_year = CRS_RELEASES[-1][1]
    if as_of_date:
        try:
            requested_date = date.fromisoformat(as_of_date)
        except ValueError:
            return ProvisionResult(found=False)
        eligible_releases = [release for release in CRS_RELEASES if release[0] <= requested_date]
        if not eligible_releases:
            return ProvisionResult(
                found=False,
                coverage_gap=True,
                version=f"C.R.S. {CRS_RELEASES[0][1]}",
                version_effective_date=CRS_RELEASES[0][0].isoformat(),
            )
        _, crs_year = eligible_releases[-1]
    if not citation.section or re.search(r"\s+(?:to|through)\s+", citation.text, re.IGNORECASE):
        return ProvisionResult(found=False, version=f"C.R.S. {crs_year}")
    match = re.fullmatch(r"(?P<section>\d{1,2}-\d{1,3}-\d+[A-Za-z]?)(?P<subsection>(?:\([0-9A-Za-z.]+\))*)", citation.section)
    if not match:
        return ProvisionResult(found=False, version=f"C.R.S. {crs_year}")
    section = match.group("section")
    subsection = citation.subsection or match.group("subsection") or None
    title = section.split("-", 1)[0]
    source_url = f"{CRS_BASE_URL}/crs{crs_year}-title-{int(title):02d}.htm"
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=20, follow_redirects=True)
    try:
        response = await client.get(source_url)
        response.raise_for_status()
    finally:
        if owns_client:
            await client.aclose()

    text = _section_text(response.text, section)
    digest = hashlib.sha256(response.content).hexdigest()
    document_header = " ".join(BeautifulSoup(response.text, "html.parser").get_text(" ").split())[:500]
    edition_match = re.search(r"Colorado Revised Statutes\s+(20\d{2})", document_header, re.IGNORECASE)
    if edition_match is None or int(edition_match.group(1)) != crs_year:
        detected_year = edition_match.group(1) if edition_match else "unknown"
        return ProvisionResult(
            found=False,
            source_url=source_url,
            source_identifier=f"crs:edition-unconfirmed:{detected_year}",
            response_sha256=digest,
        )
    if text is None:
        return ProvisionResult(found=False, version=f"C.R.S. {crs_year}", source_url=source_url, response_sha256=digest)
    confirmed_text = _subdivision_text(text, subsection) if subsection else text
    subsection_found = confirmed_text is not None
    return ProvisionResult(
        found=subsection_found, base_found=True, version=f"C.R.S. {crs_year}", source_url=source_url,
        text=confirmed_text or text, source_identifier=f"crs:{section}{subsection or ''}", response_sha256=digest,
    )


def _session_law_rows(document: str) -> list[tuple[int, str, str, str]]:
    rows: list[tuple[int, str, str, str]] = []
    for row in BeautifulSoup(document, "html.parser").select("table tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        page_text = cells[2].get_text(" ", strip=True).replace(",", "")
        link = cells[4].find("a", href=True)
        if not page_text.isdigit() or link is None:
            continue
        rows.append((int(page_text), cells[0].get_text(" ", strip=True), cells[3].get_text(" ", strip=True), link["href"]))
    return rows


def _colorado_neutral_key(value: str) -> str | None:
    match = re.fullmatch(
        r"\s*(?P<year>(?:20)?\d{2})\s*(?P<reporter>COA?)\s*(?P<number>\d+[A-Za-z]?)\s*",
        value,
        re.IGNORECASE,
    )
    if match is None:
        return None
    year = int(match.group("year"))
    if year < 100:
        year += 2000
    return f"{year}{match.group('reporter').casefold()}{match.group('number').casefold()}"


def _preserve_source(content: bytes, package_dir: Path, extension: str) -> str:
    digest = hashlib.sha256(content).hexdigest()
    package_dir.mkdir(parents=True, exist_ok=True)
    package_path = package_dir / f"{digest}.{extension}"
    if not package_path.exists():
        package_path.write_bytes(content)
    if hashlib.sha256(package_path.read_bytes()).hexdigest() != digest:
        raise OSError("Preserved Colorado legal-source package hash does not match the downloaded source")
    return digest


def _preserve_pdf(content: bytes, package_dir: Path) -> str:
    return _preserve_source(content, package_dir, "pdf")


async def _verify_colorado_case_law_archive(
    citation: ExtractedCitation,
    expected_key: str,
    court_id: str,
    court_name: str,
    docket_pattern: str,
    client: httpx.AsyncClient,
    package_dir: Path,
    search_text: str | None = None,
) -> ProvisionResult:
    search_response = await client.get(
        f"{COLORADO_CASE_LAW_SEARCH_URL}/search.json",
        headers=COLORADO_CASE_LAW_SEARCH_HEADERS,
        params={
            "product_id": "WW",
            "jurisdiction": "US",
            "content_type": "2",
            "court": court_id,
            "textolibre": search_text or f'"{citation.text}"',
            "bypass_rabl": "true",
            "include": "parent,abstract,snippet,properties_with_ids",
            "per_page": "3",
            "page": "1",
            "sort": "score",
            "type": "document",
            "include_local_exclusive": "true",
            "locale": "en",
            "hide_ct6": "true",
        },
    )
    search_response.raise_for_status()
    results = search_response.json().get("results", [])

    for result in results[:3]:
        document_id = str(result.get("id", ""))
        if not document_id.isdigit():
            continue
        document_url = f"{COLORADO_CASE_LAW_SEARCH_URL}/en/vid/{document_id}"
        document_response = await client.get(
            f"{COLORADO_CASE_LAW_SEARCH_URL}/vid/{document_id}/content",
            params={"include": "navigation", "locale": "en", "hide_ct6": "true"},
        )
        document_response.raise_for_status()
        document_text = " ".join(
            BeautifulSoup(document_response.text, "html.parser").get_text(" ").split()
        )
        header_text = document_text[:2500]
        neutral_match = re.search(
            r"(?:20)?\d{2}\s*COA?\s*\d+[A-Za-z]?",
            header_text,
            re.IGNORECASE,
        )
        docket_match = re.search(docket_pattern, header_text, re.IGNORECASE)
        if (
            neutral_match is None
            or _colorado_neutral_key(neutral_match.group()) != expected_key
            or court_name.casefold() not in header_text.casefold()
            or docket_match is None
            or re.search(r"\bSUMMARY\b", header_text[:1000])
        ):
            continue

        digest = _preserve_source(document_response.content, package_dir, "html")
        docket = docket_match.group().upper()
        return ProvisionResult(
            found=True,
            base_found=True,
            version=f"Official Colorado Case Law Search opinion ({citation.text})",
            source_url=document_url,
            text=document_text,
            source_identifier=f"colorado-case-law:{expected_key}:{docket}:vid-{document_id}",
            response_sha256=digest,
        )

    return ProvisionResult(
        found=False,
        coverage_gap=True,
        source_url=str(search_response.url),
        response_sha256=hashlib.sha256(search_response.content).hexdigest(),
    )


def _normalized_citation(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _search_result_citations(result: dict) -> list[str]:
    citations: list[str] = []
    for prop in result.get("properties", []):
        if not isinstance(prop, dict):
            continue
        label = str(prop.get("property", {}).get("label", "")).casefold()
        if label not in {"citation", "citations"}:
            continue
        for value in prop.get("values", []):
            if isinstance(value, str):
                citations.append(value)
            elif isinstance(value, dict) and isinstance(value.get("value"), str):
                citations.append(value["value"])
    return citations


async def verify_colorado_case_search(
    citation: ExtractedCitation,
    client: httpx.AsyncClient | None = None,
    opinions_dir: str | None = None,
) -> ProvisionResult:
    cache_key = f"case_search:{citation.text}"
    if cache_key in _COLORADO_SEARCH_CACHE:
        return _COLORADO_SEARCH_CACHE[cache_key]
    if opinions_dir is None:
        opinions_dir = getattr(settings, "colorado_opinions_dir", "data/colorado_opinions")
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=2.0, follow_redirects=True)
    package_dir = Path(opinions_dir) / "packages"
    try:
        search_term = (
            f"{citation.volume} {citation.reporter} {citation.reporter_page}"
            if citation.volume and citation.reporter and citation.reporter_page
            else citation.text.strip()
        )
        search_response = await client.get(
            f"{COLORADO_CASE_LAW_SEARCH_URL}/search.json",
            headers=COLORADO_CASE_LAW_SEARCH_HEADERS,
            params={
                "product_id": "WW",
                "jurisdiction": "US",
                "content_type": "2",
                "court": "14024_01,14024_02",
                "textolibre": search_term,
                "bypass_rabl": "true",
                "include": "parent,abstract,snippet,properties_with_ids",
                "per_page": "10",
                "page": "1",
                "sort": "score",
                "type": "document",
                "include_local_exclusive": "true",
                "locale": "en",
                "hide_ct6": "true",
            },
        )
        search_response.raise_for_status()
        results = search_response.json().get("results", [])
        norm_cite = _normalized_citation(search_term)

        for result in results[:10]:
            document_id = str(result.get("id", ""))
            if not document_id.isdigit():
                continue
            citations_list = _search_result_citations(result)
            matched_cite = any(_normalized_citation(c) == norm_cite for c in citations_list)
            snippet = BeautifulSoup(
                result.get("snippet", ""), "html.parser"
            ).get_text(" ")
            title = result.get("title", "")

            if matched_cite or norm_cite in _normalized_citation(snippet) or norm_cite in _normalized_citation(title):
                document_url = f"{COLORADO_CASE_LAW_SEARCH_URL}/en/vid/{document_id}"
                document_response = await client.get(
                    f"{COLORADO_CASE_LAW_SEARCH_URL}/vid/{document_id}/content",
                    params={"include": "navigation", "locale": "en", "hide_ct6": "true"},
                )
                document_response.raise_for_status()
                document_text = " ".join(
                    BeautifulSoup(document_response.text, "html.parser").get_text(" ").split()
                )
                digest = _preserve_source(document_response.content, package_dir, "html")
                court_name = result.get("parent", {}).get("title") or "Colorado Judicial Branch"

                return ProvisionResult(
                    found=True,
                    base_found=True,
                    version=f"Official Colorado Case Law Search ({court_name})",
                    source_url=document_url,
                    text=document_text,
                    source_identifier=f"colorado-case-law:{title or search_term}:vid-{document_id}",
                    response_sha256=digest,
                )

        return ProvisionResult(
            found=False,
            coverage_gap=False,
            source_url=str(search_response.url),
            response_sha256=hashlib.sha256(search_response.content).hexdigest(),
        )
    finally:
        if owns_client:
            await client.aclose()


async def verify_colorado_court_of_appeals(
    citation: ExtractedCitation,
    client: httpx.AsyncClient | None = None,
    opinions_dir: str | None = None,
) -> ProvisionResult:
    cache_key = f"coa:{citation.text}"
    if cache_key in _COLORADO_SEARCH_CACHE:
        return _COLORADO_SEARCH_CACHE[cache_key]
    if opinions_dir is None:
        opinions_dir = settings.colorado_opinions_dir
    expected_key = _colorado_neutral_key(citation.text)
    party_query = citation.case_name.split("v.")[0].strip() if citation.case_name else None
    search_term = expected_key.upper() if expected_key else party_query
    if not search_term:
        return ProvisionResult(found=False)

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=2.0, follow_redirects=True)
    package_dir = Path(opinions_dir) / "packages"
    try:
        search_response = await client.get(
            COLORADO_COURT_OF_APPEALS_ANNOUNCEMENTS_URL,
            params={"search_api_fulltext": search_term},
        )
        search_response.raise_for_status()
        search = BeautifulSoup(search_response.text, "html.parser")
        node_links = [
            link for link in search.find_all("a", href=True)
            if re.fullmatch(r"/node/\d+", link["href"])
        ]
        for node_link in node_links:
            node_url = urljoin(COLORADO_COURT_OF_APPEALS_ANNOUNCEMENTS_URL, node_link["href"])
            node_response = await client.get(node_url)
            node_response.raise_for_status()
            node = BeautifulSoup(node_response.text, "html.parser")
            announcement_link = next(
                (
                    link for link in node.find_all("a", href=True)
                    if re.search(r"/sites/default/files/.+\.pdf$", link["href"], re.IGNORECASE)
                ),
                None,
            )
            if announcement_link is None:
                continue
            announcement_url = urljoin(node_url, announcement_link["href"])
            announcement_response = await client.get(announcement_url)
            announcement_response.raise_for_status()
            if not announcement_response.content.startswith(b"%PDF"):
                continue
            _preserve_pdf(announcement_response.content, package_dir)

            with fitz.open(stream=announcement_response.content, filetype="pdf") as announcement:
                announcement_text = " ".join(" ".join(page.get_text().split()) for page in announcement)
                announcement_docket = None
                if expected_key:
                    neutral_matches = list(re.finditer(
                        r"(?:20)?\d{2}\s*COA\s*\d+[A-Za-z]?",
                        announcement_text,
                        re.IGNORECASE,
                    ))
                    citation_matches = {_colorado_neutral_key(match.group()) for match in neutral_matches}
                    if expected_key not in citation_matches:
                        continue
                    for index, match in enumerate(neutral_matches):
                        if _colorado_neutral_key(match.group()) != expected_key:
                            continue
                        end = neutral_matches[index + 1].start() if index + 1 < len(neutral_matches) else len(announcement_text)
                        docket_match = re.search(
                            r"(?:Court of Appeals )?(?:Case )?No\.\s*(\d{2}CA\d+)",
                            announcement_text[match.start() : end],
                            re.IGNORECASE,
                        )
                        if docket_match:
                            announcement_docket = docket_match.group(1).upper()
                        break
                elif party_query:
                    if party_query.lower() not in announcement_text.lower():
                        continue

                opinion_urls = [
                    link["uri"]
                    for page in announcement
                    for link in page.get_links()
                    if link.get("uri") and re.search(r"\.pdf(?:$|\?)", link["uri"], re.IGNORECASE)
                ]
            if not opinion_urls:
                return ProvisionResult(
                    found=False,
                    coverage_gap=True,
                    source_url=announcement_url,
                    source_identifier=f"colorado-judicial:{expected_key or 'party'}:announcement-{Path(node_link['href']).name}",
                    response_sha256=hashlib.sha256(announcement_response.content).hexdigest(),
                )
            for opinion_url in dict.fromkeys(opinion_urls):
                opinion_response = await client.get(opinion_url)
                opinion_response.raise_for_status()
                if not opinion_response.content.startswith(b"%PDF"):
                    continue
                digest = _preserve_pdf(opinion_response.content, package_dir)
                with fitz.open(stream=opinion_response.content, filetype="pdf") as opinion:
                    opinion_text = " ".join(" ".join(page.get_text().split()) for page in opinion)
                    header_text = " ".join(opinion[0].get_text().split())[:2500] if len(opinion) else ""
                if expected_key:
                    header_citations = {
                        _colorado_neutral_key(match.group())
                        for match in re.finditer(r"(?:20)?\d{2}\s*COA\s*\d+[A-Za-z]?", header_text, re.IGNORECASE)
                    }
                    if expected_key not in header_citations:
                        continue
                elif party_query:
                    if party_query.lower() not in header_text.lower():
                        continue
                docket_match = re.search(
                    r"(?:Court of Appeals )?(?:Case )?No\.\s*(\d{2}CA\d+)",
                    header_text,
                    re.IGNORECASE,
                )
                docket = docket_match.group(1).upper() if docket_match else "SLIP"
                return ProvisionResult(
                    found=True,
                    base_found=True,
                    version=f"Official Colorado Court of Appeals slip opinion ({citation.text})",
                    source_url=opinion_url,
                    text=opinion_text,
                    source_identifier=f"colorado-judicial:{expected_key or 'party'}:{docket}:announcement-{Path(node_link['href']).name}",
                    response_sha256=digest,
                )
            if announcement_docket:
                archived = await _verify_colorado_case_law_archive(
                    citation,
                    expected_key,
                    "14024_02",
                    "Colorado Court of Appeals",
                    r"\b\d{2}CA\d+\b",
                    client,
                    package_dir,
                    search_text=announcement_docket,
                )
                if archived.found:
                    return archived
            return ProvisionResult(
                found=False,
                base_found=True,
                source_url=announcement_url,
                source_identifier=f"colorado-judicial:{expected_key}:announcement-{Path(node_link['href']).name}",
                response_sha256=hashlib.sha256(announcement_response.content).hexdigest(),
            )
        return ProvisionResult(
            found=False,
            coverage_gap=True,
            source_url=str(search_response.url),
            response_sha256=hashlib.sha256(search_response.content).hexdigest(),
        )
    finally:
        if owns_client:
            await client.aclose()


async def verify_colorado_supreme_court(
    citation: ExtractedCitation,
    client: httpx.AsyncClient | None = None,
    opinions_dir: str | None = None,
) -> ProvisionResult:
    cache_key = f"sc:{citation.text}"
    if cache_key in _COLORADO_SEARCH_CACHE:
        return _COLORADO_SEARCH_CACHE[cache_key]
    if opinions_dir is None:
        opinions_dir = getattr(settings, "colorado_opinions_dir", "data/colorado_opinions")
    if citation.reporter != "CO" or not citation.volume or not citation.reporter_page:
        return ProvisionResult(found=False)
    expected_key = _colorado_neutral_key(citation.text)
    if expected_key is None:
        return ProvisionResult(found=False)

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=2.0, follow_redirects=True)
    try:
        listing_response = await client.get(COLORADO_SUPREME_COURT_OPINIONS_URL)
        listing_response.raise_for_status()
        listing = BeautifulSoup(listing_response.text, "html.parser")
        opinion_link = next(
            (
                link
                for link in listing.find_all("a", href=True)
                if _colorado_neutral_key(link.get_text(" ", strip=True)) == expected_key
            ),
            None,
        )
        if opinion_link is None:
            return await _verify_colorado_case_law_archive(
                citation,
                expected_key,
                "14024_01",
                "Supreme Court of Colorado",
                r"\b\d{2}(?:SC|SA)\d+[A-Za-z]?\b",
                client,
                Path(opinions_dir) / "packages",
            )

        node_url = urljoin(COLORADO_SUPREME_COURT_OPINIONS_URL, opinion_link["href"])
        node_response = await client.get(node_url)
        node_response.raise_for_status()
        node = BeautifulSoup(node_response.text, "html.parser")
        pdf_link = next(
            (
                link
                for link in node.find_all("a", href=True)
                if re.search(r"/system/files/opinions-[^/]+/[^/]+\.pdf$", link["href"], re.IGNORECASE)
            ),
            None,
        )
        if pdf_link is None:
            return ProvisionResult(
                found=False,
                source_url=node_url,
                response_sha256=hashlib.sha256(node_response.content).hexdigest(),
            )

        source_url = urljoin(node_url, pdf_link["href"])
        pdf_response = await client.get(source_url)
        pdf_response.raise_for_status()
        content = pdf_response.content
        digest = _preserve_pdf(content, Path(opinions_dir) / "packages")

        with fitz.open(stream=content, filetype="pdf") as document:
            opinion_text = " ".join(" ".join(page.get_text().split()) for page in document)
        docket = Path(pdf_link["href"]).stem
        citation_confirmed = expected_key in {
            _colorado_neutral_key(match.group())
            for match in re.finditer(r"(?:20)?\d{2}\s+CO\s+\d+[A-Za-z]?", opinion_text, re.IGNORECASE)
        }
        docket_confirmed = re.search(rf"\b{re.escape(docket)}\b", opinion_text, re.IGNORECASE) is not None
        return ProvisionResult(
            found=citation_confirmed and docket_confirmed,
            base_found=True,
            version=f"Official Colorado Supreme Court slip opinion ({citation.text})",
            source_url=source_url,
            text=opinion_text,
            source_identifier=f"colorado-judicial:{expected_key}:{docket}",
            response_sha256=digest,
        )
    finally:
        if owns_client:
            await client.aclose()


async def verify_session_law(
    citation: ExtractedCitation,
    client: httpx.AsyncClient | None = None,
    session_laws_dir: str | None = None,
) -> ProvisionResult:
    if session_laws_dir is None:
        session_laws_dir = getattr(settings, "session_laws_dir", "data/session_laws")
    if not citation.volume or not citation.reporter_page:
        return ProvisionResult(found=False)
    try:
        year = int(citation.volume)
        cited_page = int(citation.reporter_page)
    except ValueError:
        return ProvisionResult(found=False)
    version = f"{year} Colorado Session Laws"
    if year < 2016 or year > date.today().year:
        return ProvisionResult(found=False, coverage_gap=True, version=version)

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=2.0, follow_redirects=True)
    candidate: tuple[int, str, str, str] | None = None
    try:
        for page_number in range(100):
            response = await client.get(
                SESSION_LAWS_URL,
                params={"sess": f"{year}a", "sort": "page_asc", "page": page_number},
            )
            response.raise_for_status()
            rows = _session_law_rows(response.text)
            if not rows:
                break
            for row in rows:
                if row[0] > cited_page:
                    break
                candidate = row
            if any(row[0] > cited_page for row in rows) or len(rows) < 25:
                break
        if candidate is None:
            return ProvisionResult(found=False, version=version, source_url=SESSION_LAWS_URL)

        start_page, measure, chapter, href = candidate
        source_url = urljoin(SESSION_LAWS_URL, href)
        pdf_response = await client.get(source_url)
        pdf_response.raise_for_status()
        content = pdf_response.content
        digest = hashlib.sha256(content).hexdigest()
        package_dir = Path(session_laws_dir) / "packages"
        package_dir.mkdir(parents=True, exist_ok=True)
        package_path = package_dir / f"{digest}.pdf"
        if not package_path.exists():
            package_path.write_bytes(content)
        if hashlib.sha256(package_path.read_bytes()).hexdigest() != digest:
            raise OSError("Preserved Colorado Session Laws package hash does not match the downloaded PDF")

        matching_text = None
        document_text: list[str] = []
        with fitz.open(stream=content, filetype="pdf") as document:
            for page in document:
                text = " ".join(page.get_text().split())
                document_text.append(text)
                margin_text = " ".join(
                    block[4]
                    for block in page.get_text("blocks")
                    if block[3] <= 110 or block[1] >= page.rect.height - 110
                )
                if re.search(rf"(?:^|\s){cited_page}(?:\s|$)", margin_text):
                    matching_text = text
        full_text = " ".join(document_text)
        measure_number = measure.split()[0]
        measure_match = re.fullmatch(r"(?P<chamber>HB|SB)(?P<number>\d{2}-\d+)", measure_number, re.IGNORECASE)
        chamber_pattern = "(?:HB|HOUSE BILL)" if measure_match and measure_match.group("chamber").casefold() == "hb" else "(?:SB|SENATE BILL)"
        measure_confirmed = bool(measure_match) and re.search(
            rf"\b{chamber_pattern}\s*{re.escape(measure_match.group('number'))}\b",
            full_text,
            re.IGNORECASE,
        ) is not None
        chapter_confirmed = re.search(rf"\bCh(?:apter)?\.?\s*{re.escape(chapter)}\b", full_text, re.IGNORECASE) is not None
        found = matching_text is not None and measure_confirmed and chapter_confirmed
        return ProvisionResult(
            found=found,
            base_found=True,
            version=f"{version}, ch. {chapter}",
            source_url=source_url,
            text=matching_text,
            source_identifier=f"colorado-session-laws:{year}:{cited_page}:ch-{chapter}:{measure.split()[0]}",
            response_sha256=digest,
        )
    finally:
        if owns_client:
            await client.aclose()
