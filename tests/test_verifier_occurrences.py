from caselaw.group import group_citations
from caselaw.verifier_client import to_case_payload


def test_quote_owner_and_full_group_survive_proxy_mapping():
    text = ('United States v. Carloss, 818 F.3d 988 (10th Cir. 2016). '
            'The court wrote "I respectfully dissent." Id. at 1008 (Gorsuch, J., dissenting).')
    group = group_citations(text).groups[0].as_dict()
    payload = to_case_payload(group)
    assert payload["case_name"] == "United States v. Carloss"
    assert len(payload["occurrences"]) == 1 + len(group["children"])
    quote = payload["quotes"][0]
    owner = next(c for c in payload["occurrences"] if c["occurrence_id"] == quote["citation_occurrence_id"])
    assert owner["source_span"] == list(group["quotes"][0]["citation_span"])
    assert "1008" in owner["pin_cite"]
    assert quote["source_span"] == list(group["quotes"][0]["span"])


def test_legacy_flattened_payload_still_works():
    payload = to_case_payload({"groupId": "g", "volume": 556, "reporter": "U.S.", "page": 662,
                               "caseName": "Ashcroft v. Iqbal", "quotes": [{"text": "quote"}]})
    assert payload["quotes"] == [{"text": "quote"}]
