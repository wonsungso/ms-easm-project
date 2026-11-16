from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pptx import Presentation

from easm_agent.models import AssessmentMeasurement, Collection, Finding
from easm_agent.report_pptx import TITLE, write_presentation

NOW = datetime(2026, 11, 16, tzinfo=UTC)


def finding(code: str, level: str, numerator: float | None = None, denominator: float | None = None,
            reason: str | None = None) -> Finding:
    ratio = None if numerator is None else numerator / denominator
    return Finding(
        se_code=code, scope="partial", level=level, metric_value=ratio, reason=reason, rationale="fixture",
        level_criterion=None if level == "N/A" else f"{code} 충족 비율",
        next_step="다음 단계 조건: 80% 이상" if level in ("L1", "L2") else None,
        measurement=AssessmentMeasurement(numerator=numerator, denominator=denominator, complete=ratio is not None),
    )


def texts(path: Path) -> list[str]:
    deck = Presentation(path)
    return [shape.text_frame.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame]


def test_deck_uses_fixed_title_without_subtitle_and_reports_counts(tmp_path: Path) -> None:
    rows = [
        finding("DS-SY-05", "L5", 9, 9), finding("DS-SY-07", "L2", 1, 3), finding("BI-SY-10", "L1", 0, 1),
        finding("DM-SY-01", "N/A", reason="permission_denied"),
    ]
    path = tmp_path / "deck.pptx"
    write_presentation(Collection(collected_at=NOW), rows, path)
    content = texts(path)
    assert content[0] == TITLE == "EASM (Enterprise Agent Service Management) 점검 결과 보고서"
    assert "경영진 보고" not in "\n".join(content)
    joined = "\n".join(content)
    assert "4개 점검 항목 중 3개를 진단했고, 1개가 최고 수준(L5)입니다" in joined
    assert "권한 또는 라이선스 문제로 조회 거부" in joined and "1/3" in joined
    assert not any(token in joined for token in ("Lorem", "Click to", "Label"))


@pytest.mark.parametrize("rows", [
    [],
    [finding("DM-SY-01", "N/A", reason="error")],
    [finding("DS-SY-05", "L5", 3, 3)],
])
def test_deck_is_written_for_empty_pending_only_and_all_strong_results(tmp_path: Path, rows: list[Finding]) -> None:
    path = tmp_path / "deck.pptx"
    write_presentation(Collection(collected_at=NOW), rows, path)
    assert len(Presentation(path).slides) >= 8
