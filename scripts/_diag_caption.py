import importlib
import sys

sys.path.insert(0, ".")
E = importlib.import_module("caselaw.extract")

CASES = [
    ("plain", "Smith v. Jones, "),
    ("docket_No", "Rivero v. Bd. of Regents of Univ. of New Mexico, No. CIV 16-0318 JB/SCY, "),
    ("docket_No_short", "Rivero v. Bd. of Regents, No. CIV 16-0318, "),
    ("docket_no_period", "Rivero v. Bd. of Regents of Univ. of New Mexico, No CIV 16-0318, "),
    ("case_no", "Smith v. Jones, Case No. 1:22-cv-01129, "),
    ("sentence_then_name", "the rule is settled. Smith v. Jones, "),
    ("stamp_split", "Robinson  Case No. 1:22-cv-01129-NYW-SBP  Document 283    filed 02/25/25  USDC Colorado\n                                  pg 2 of 17\n\n\n\n\nv. Mo. Pac. R.R. Co., "),
    ("line_split_v", "Union Pac. R.R. Co.\nv. Mo. Pac. R.R. Co., "),
    ("nested_paren", "CF&I Steel, L.P. v. United Steel Workers of Am., 23 P.3d 1197, 1200 (Colo. 2001)), report and recommendation adopted, "),
]

for name, window in CASES:
    print(f"--- {name}")
    print(f"    window  = {window!r}")
    print(f"    parties = {E._derive_parties(window)}")
    after = E._after_last_sentence(E._after_section_heading(window))
    print(f"    after   = {after!r}")
    stripped = E._strip_emphasis_markers(E._normalize_docket_slashes(after).rstrip())
    m = E._CASE_NAME.search(stripped)
    print(f"    match   = {m.groups() if m else None}")
    print(f"    casename= {E._derive_case_name(window)}")
