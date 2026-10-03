"""Write a battery of small synthetic probe documents under output/probes/.

One file per shape, so each probe is an isolated document. Untracked scratch.

Usage: python scripts/make_probes.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "probes"

PROBES: dict[str, str] = {
    "01_shortname_signal": "See Bell Atlantic Corp., 550 U.S. 544, 556 (2007).\n",
    "02_plain_v": "See also Ashcroft v. Iqbal, 556 U.S. 662, 678 (2009).\n",
    "03_short_with_pin": "The rule is settled. Smith v. Jones, 5 P.3d 1, 4 (Colo. 2000).\n",
    "04_glued_versus": (
        "The court so held. Rectorv. City and County of Denver, 122 P.3d 1010 "
        "(Colo. App. 2005), certiorari denied, 549 U.S. 1001 (2006).\n"
    ),
    "05_priv_abbrev_first": "See Priv. Corp. v. Smith, 5 P.3d 1, 3 (Colo. 2000).\n",
    "06_gov_abbrev": "See Gov. Brown v. Smith, 5 P.3d 1, 3 (Colo. 2000).\n",
    "07_markdown": "*Warne v. Hall*, 373 P.3d 596, 600 (Colo. 2016).\n",
    "08_in_re": "In re Estate of Smith, 5 P.3d 1, 3 (Colo. 2000).\n",
    "09_page_mark": "P13 County of Sacramento v. Lewis, 523 U.S. 833, 846 (1998).\n",
    "10_stamp_heading": "NOT A FILED PLEADING\nSmith v. Jones, 5 P.3d 1, 4 (Colo. 2000).\n",
    "11_draft_heading": "DRAFT\nSmith v. Jones, 5 P.3d 1, 4 (Colo. 2000).\n",
    "12_toa_heading": (
        "TABLE OF AUTHORITIES\nCases\nSmith v. Jones, 5 P.3d 1, 4 (Colo. 2000).\n"
    ),
    "13_under_leadin": (
        "Under United States v. Jones, 565 U.S. 400, 404 (2012), the rule applies.\n"
    ),
    "14_subsequent_history": (
        "People v. Hoff, 2016 CO 53, 375 P.3d 1214, 1219, aff'd, 908 F.3d 1219 "
        "(10th Cir. 2018).\n"
    ),
    "15_history_glued_apostrophe": (
        "Fantasy, Inc. v. Fogerty, 984 F.2d 1524 (9th Cir. 1993), rev'd on other "
        "grounds, 510 U.S. 517 (1994).\n"
    ),
    "16_docket_slash": (
        "Rivero v. Bd. of Regents of Univ. of New Mexico, No. CIV 16-0318 JB\\SCY, "
        "2019 WL 1085179, at *78 (D.N.M. Mar. 7, 2019), aff'd, 950 F.3d 754 "
        "(10th Cir. 2020).\n"
    ),
    "17_string_cite_and": (
        "See Smith, 5 P.3d 1, 4, and Brown v. White, 2 P.3d 2 (Colo. 2001).\n"
    ),
    "18_comma_comma": (
        "See Smith v. Jones, 5 P.3d 1, 4, Brown v. White, 2 P.3d 2 (Colo. 2001).\n"
    ),
    "19_id_chain": (
        "Illinois v. Wardlow, 528 U.S. 119, 124 (2000). The Court held that flight "
        "may be considered. Id. at 125.\n"
    ),
    "20_two_woo": (
        "People v. Woo, 579 P.3d 459, 465 (Colo. 2025). Woo v. El Paso County "
        "Sheriff's Office, 528 P.3d 899, 902 (Colo. 2023). Woo, 579 P.3d at 465.\n"
    ),
    "21_entity_period": (
        "Pub. Util. Comm'n v. Colo. Motorway, Inc., 79 P.2d 1, 3 (Colo. 1938).\n"
    ),
    "22_two_cases_semicolon": (
        "A v. B, 1 P.3d 1 (Colo. 2000); see C v. D, 2 P.3d 2 (Colo. 2001).\n"
    ),
    "23_id_then_paragraph": (
        "The court has discretion. Id.\n\n   14. Any issue with the search warrant "
        "is waived.\n"
    ),
    "24_ocr_ordinal": (
        "See Shaboon v. Egyptair, 2013 IL App (Ist) 111279-U, para. 12.\n"
    ),
    "25_no_page_cite": (
        "Woo v. El Paso County Sheriff's Office, 528 P.3d (Colo., 2022).\n"
    ),
    "26_emphasis_underscore": "_Warne v. Hall_, 373 P.3d 596, 600 (Colo. 2016).\n",
    "27_corp_short_name": (
        "See Bell Atlantic Corp., 550 U.S. at 556 (2007).\n"
    ),
    "28_history_argued": (
        "Smith v. Jones, 5 P.3d 1 (Colo. 2000), argued, Brown v. White, 2 P.3d 2 "
        "(Colo. 2001).\n"
    ),
    "29_rev_proc": (
        "See Rev. Proc. 2020-1, 2020-1 C.B. 1. Smith v. Jones, 5 P.3d 1 (Colo. 2000).\n"
    ),
    "30_nov_date": (
        "Smith v. Jones, 5 P.3d 1, 3 (Colo. Nov. 4, 2000). See also Brown v. "
        "White, 2 P.3d 2 (Colo. 2001).\n"
    ),
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in PROBES.items():
        (OUT / f"{name}.txt").write_text(body, encoding="utf-8")
    print(f"wrote {len(PROBES)} probes to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
