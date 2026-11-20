from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from easm_agent.assessment_codes import ASSESSMENT_REVISION
from easm_agent.models import load_criteria
from easm_agent.report import load_result
from easm_agent.report_template import CRITERIA_SHEET, assessment_template_path


def test_system_evidence_codes_use_one_continuous_se_sequence() -> None:
    expected = [
        f"{prefix}-SY-{number:02}"
        for prefix, start, end in (
            ("DM", 1, 1), ("DS", 2, 7), ("BI", 8, 14),
            ("DP", 15, 15), ("OE", 16, 22), ("OT", 23, 26),
        )
        for number in range(start, end + 1)
    ]
    assert list(load_criteria()["items"]) == expected
    sheet = load_workbook(assessment_template_path())[CRITERIA_SHEET]
    assert [row[1].value for row in sheet if "-SY-" in str(row[1].value)] == expected


def test_saved_result_preserves_scores_evidence_and_snapshots(tmp_path: Path) -> None:
    codes = list(load_criteria()["items"])
    payload = {
        "schema_version": 1,
        "collection": {
            "facts": {"assessment_revision": ASSESSMENT_REVISION},
            "agents": [{"se_codes": codes}],
            "assessment_provenance": {"criteria_snapshot": {"items": dict.fromkeys(codes, "original")}},
        },
        "findings": [
            {"se_code": code, "level": "L3", "metric_value": 0.85, "evidence_refs": ["evidence:original"]}
            for code in codes
        ],
        "evidence": {"original": {"payload": "original evidence"}},
    }
    source = tmp_path / "raw-data-20261117T000000Z.json"
    original = json.dumps(payload)
    source.write_text(original, encoding="utf-8")
    assert load_result(tmp_path) == payload
    assert source.read_text(encoding="utf-8") == original


def test_unknown_revision_is_explicitly_rejected(tmp_path: Path) -> None:
    payload = {"schema_version": 1, "collection": {"facts": {"assessment_revision": 99}}}
    (tmp_path / "raw-data-20261117T000000Z.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="지원되지 않는 심사 기준 버전"):
        load_result(tmp_path)


def test_unknown_evidence_code_is_rejected_without_changing_the_file(tmp_path: Path) -> None:
    payload = {
        "schema_version": 1, "collection": {"facts": {"assessment_revision": ASSESSMENT_REVISION}},
        "findings": [{"se_code": "DM-XX-01", "level": "L3"}],
    }
    source = tmp_path / "raw-data-20261117T000000Z.json"
    original = json.dumps(payload)
    source.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match="알 수 없는 System Evidence 코드"):
        load_result(tmp_path)
    assert source.read_text(encoding="utf-8") == original
