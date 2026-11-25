from pathlib import Path

import pytest


@pytest.fixture
def legacy_report_template(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Exercise the saved five-sheet report contract, not the current default template."""
    from easm_agent import report_template

    path = Path(__file__).parent / "fixtures" / "legacy-assessment-template.xlsx"
    monkeypatch.setattr(report_template, "assessment_template_path", lambda: path)
    if hasattr(request.module, "assessment_template_path"):
        monkeypatch.setattr(request.module, "assessment_template_path", lambda: path)


@pytest.fixture
def legacy_presentation_template(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Keep prior 12-slide shape-contract regressions separate from the new Biz default."""
    from easm_agent import report_pptx

    path = Path(__file__).parent / "fixtures" / "legacy-assessment-report-template.pptx"
    monkeypatch.setattr(report_pptx, "presentation_template_path", lambda: path)
    if hasattr(request.module, "presentation_template_path"):
        monkeypatch.setattr(request.module, "presentation_template_path", lambda: path)
