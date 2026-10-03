"""Write a second battery: party names that collide with the lead-in stripper.

Usage: python scripts/make_probes2.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "probes2"

PROBES: dict[str, str] = {
    "01_circuit_city": "Circuit City Stores, Inc. v. Adams, 532 U.S. 105, 119 (2001).\n",
    "02_court_of_appeals": "Court of Appeals v. Smith, 5 P.3d 1 (Colo. 2000).\n",
    "03_and_anderson": "And Anderson, Inc. v. Smith, 5 P.3d 1 (Colo. 2000).\n",
    "04_also_alsop": "Also v. Smith, 5 P.3d 1 (Colo. 2000).\n",
    "05_in_internet": "In re Marriage of Smith, 5 P.3d 1 (Colo. 2000).\n",
    "06_court_courtland": "Courtland v. Smith, 5 P.3d 1 (Colo. 2000).\n",
    "07_seeing_eye": "See v. Smith, 5 P.3d 1 (Colo. 2000).\n",
    "08_generally_electric": "General Electric Co. v. Smith, 5 P.3d 1 (Colo. 2000).\n",
    "09_under_underwood": "Underwood v. Smith, 5 P.3d 1 (Colo. 2000).\n",
    "10_no_numbering": "A. Smith v. Jones, 5 P.3d 1 (Colo. 2000).\n",
    "11_ex_parte": "Ex parte Young, 209 U.S. 123 (1908).\n",
    "12_people_in_interest": (
        "People in the Interest of C.A.G., 903 P.2d 1229, 1231 (Colo. App. 1995).\n"
    ),
    "13_corp_v_corp": (
        "Bell Atlantic Corp. v. Twombly, 550 U.S. 544, 556 (2007). "
        "See also Twombly, 550 U.S. at 557.\n"
    ),
    "14_city_of": "City of Los Angeles v. Patel, 576 U.S. 409, 415 (2015).\n",
    "15_state_of": "State of Colorado v. Smith, 5 P.3d 1 (Colo. 2000).\n",
    "16_dep't": (
        "Dep't of Revenue v. Smith, 5 P.3d 1 (Colo. 2000).\n"
    ),
    "17_rev_abbrev": (
        "Rev. Rul. 2020-1 does not apply. Smith v. Jones, 5 P.3d 1 (Colo. 2000).\n"
    ),
    "18_priv_abbrev_mid": (
        "See In re Facebook, Inc. Consumer Priv. User Profile Litig., "
        "2020 WL 614956, at *2 (N.D. Cal. Feb. 10, 2020).\n"
    ),
    "19_fed_r_evid": (
        "Fed. R. Evid. 403 governs. Old Chief v. United States, 519 U.S. 172, 180 "
        "(1997).\n"
    ),
    "20_supra": (
        "Bell Atlantic Corp. v. Twombly, 550 U.S. 544, 556 (2007). "
        "Twombly, supra, at 557.\n"
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
