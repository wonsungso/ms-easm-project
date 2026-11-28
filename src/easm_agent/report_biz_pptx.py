"""Populate the business-linked 27-slide deck from observed and manually entered evidence."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean

from openpyxl import load_workbook
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.shapes.base import BaseShape
from pptx.shapes.graphfrm import GraphicFrame
from pptx.shapes.group import GroupShape
from pptx.slide import Slide
from pptx.util import Inches, Pt

from easm_agent import report_narrative as story
from easm_agent.deck_model import AREAS, _score
from easm_agent.report_backdata import ReportMetric
from easm_agent.report_integrated import GRADES, KST, PROCESS, RAW, is_integrated
from easm_agent.report_story import DEFAULT_CUSTOMER, PENDING_LABEL, DeckData, pct

BIZ_SLIDE_COUNT = 27
PENDING = PENDING_LABEL
FOOTNOTE = "API 구성·기록의 조회 범위만 평가하며 정책 승인·실효성·전사 성숙도를 증명하지 않습니다."


@dataclass(frozen=True)
class ManualEvidence:
    documents: tuple[tuple[str, str, object, object, object, object, object], ...]
    interviews: tuple[tuple[str, ...], ...]
    overview: dict[str, object]
    raw_scores: tuple[int, ...]
    caps: tuple[int, ...]


def read_manual_evidence(path: Path) -> ManualEvidence:
    book = load_workbook(path)
    if not is_integrated(book):
        book.close()
        return ManualEvidence((), (), {}, (), ())
    documents = tuple(
        (str(book["5_문서 실사"].cell(row, 1).value or ""),
         str(book["5_문서 실사"].cell(row, 3).value or ""),
         *(book["5_문서 실사"].cell(row, column).value for column in (4, 5, 6, 7, 10)))
        for row in range(5, 67)
    )
    interviews = tuple(
        tuple(str(book["6_인터뷰 기록"].cell(row, column).value or "") for column in range(1, 7))
        for row in range(5, 17)
    )
    overview = {str(book["1_진단 개요"].cell(row, 1).value): book["1_진단 개요"].cell(row, 2).value
                for row in range(5, 44) if book["1_진단 개요"].cell(row, 1).value}
    scores, caps = [], []
    for row in range(5, 59):
        response = _score(book[PROCESS].cell(row, 6).value)
        if response is None:
            continue
        scores.append(response)
        caps.append(2 if book[PROCESS].cell(row, 7).value != "Y" else
                    3 if book[PROCESS].cell(row, 8).value != "Y" else
                    4 if book[PROCESS].cell(row, 9).value != "Y" else 5)
    book.close()
    return ManualEvidence(documents, interviews, overview, tuple(scores), tuple(caps))


def workbook_metrics(path: Path) -> dict[str, ReportMetric]:
    """Keep XLSX-only deck generation useful without inventing API or business evidence."""
    book = load_workbook(path)
    metrics: dict[str, ReportMetric] = {}
    if is_integrated(book):
        for row in range(5, 31):
            code = str(book[GRADES].cell(row, 1).value)
            grade = _score(book[GRADES].cell(row, 21).value)
            ratio = book[GRADES].cell(row, 22).value if grade is not None else None
            first = (row - 5) * 2 + 5
            unit = book[RAW].cell(first, 7).value
            if book[RAW]["M4"].value == "easm_measurement_unit":
                unit = book[RAW].cell(first, 14).value or book[RAW].cell(first, 13).value
            for key, value, metric_unit in (
                ("se." + code, ratio, "ratio"),
                (f"se.{code}.numerator", book[RAW].cell(first, 6).value if grade is not None else None,
                 unit if unit not in ("count", "amount", None) else "건"),
                (f"se.{code}.denominator", book[RAW].cell(first + 1, 6).value if grade is not None else None,
                 unit if unit not in ("count", "amount", None) else "건"),
                (f"se.{code}.l3_min", book[GRADES].cell(row, 14).value, "ratio"),
            ):
                if type(value) not in (int, float):
                    continue
                metrics[key] = ReportMetric(
                    key=key, label=code, value=value, unit=str(metric_unit), status="observed",
                    reason=None, limitation="저장 Excel의 API 관측값. 실시간 재수집 아님",
                )
    book.close()
    return metrics


def workbook_collected_at(path: Path) -> datetime | None:
    book = load_workbook(path, read_only=True)
    value = None
    localized = False
    if is_integrated(book):
        source = book[RAW]
        value = source["L2"].value if source["L1"].value == "easm_collected_at_utc" else None
        if value is None:
            value = source["I5"].value
            localized = source["I4"].value == "추출 일시 (KST)"
    book.close()
    if value is None:
        return None
    if isinstance(value, datetime):
        collected = value.replace(tzinfo=KST) if localized and value.tzinfo is None else value
    elif isinstance(value, str):
        collected = datetime.fromisoformat(value)
    else:
        raise ValueError("Excel의 API 수집 시각은 날짜·시간 또는 시간대가 있는 ISO 문자열이어야 합니다.")
    if collected.tzinfo is None:
        raise ValueError("Excel의 API 수집 시각에 시간대가 없습니다.")
    return collected


def _number(value: float | int | None, *, level: bool = False) -> str:
    if value is None:
        return PENDING
    return ("L" if level else "") + f"{value:.1f}"


def _measured_text(data: DeckData, code: str) -> str:
    value = data.fraction(code) or PENDING
    ratio = data.ratio(code)
    if ratio is None:
        return value
    precision = "<0.01%" if 0 < ratio < .00005 else (
        ">99.99%·<100%" if .99995 <= ratio < 1 else f"{ratio:.2%}"
    )
    return value + " (" + precision + ")"


def _replace(slide: Slide, values: dict[int, str]) -> None:
    from easm_agent.report_pptx import replace_text

    for identifier, text in values.items():
        target = next((target for target in _walk(slide.shapes) if target.shape_id == identifier), None)
        if target is None or not target.has_text_frame:
            raise ValueError(f"{identifier}: 텍스트 도형 계약이 없습니다.")
        replace_text(target, text)


def _walk(shapes: Iterable[BaseShape]) -> Iterator[BaseShape]:
    for target in shapes:
        yield target
        if isinstance(target, GroupShape):
            yield from _walk(target.shapes)


def _remove(slide: Slide, identifiers: tuple[int, ...]) -> None:
    for target in list(_walk(slide.shapes)):
        if target.shape_id in identifiers:
            target._element.getparent().remove(target._element)


def _table(slide: Slide, identifier: int, rows: list[list[str]]) -> None:
    from easm_agent.report_pptx import replace_text

    target = _table_shape(slide, identifier)
    table = target.table
    if len(rows) > len(table.rows) or any(len(row) != len(table.columns) for row in rows):
        raise ValueError(f"{identifier}: 새 보고서 표의 행·열 계약이 다릅니다.")
    for row_index, row in enumerate(table.rows):
        for column, cell in enumerate(row.cells):
            replace_text(cell, rows[row_index][column] if row_index < len(rows) else "")


def _table_shape(slide: Slide, identifier: int) -> GraphicFrame:
    target = next((target for target in slide.shapes if target.shape_id == identifier), None)
    if not isinstance(target, GraphicFrame) or not target.has_table:
        raise ValueError(f"{identifier}: 표 도형이 아닙니다.")
    return target


def _bar(slide: Slide, identifier: int, value: float | None, *, top: bool = False, maximum: float = 5) -> None:
    from easm_agent.report_pptx import shape

    target = shape(slide, identifier)
    if value is None or value == 0:
        target._element.getparent().remove(target._element)
        return
    if not 0 <= value <= maximum:
        raise ValueError("슬라이드 그래프 값이 범위를 벗어났습니다.")
    if top:
        bottom = target.top + target.height
        target.height = Inches(value / maximum * 1.86)
        target.top = bottom - target.height
    else:
        target.width = Inches(2.57 * value / maximum)


def _manual_note(slide: Slide, identifier: int = 24610) -> None:
    _replace(slide, {identifier: "수동 입력 자료만 반영합니다. 미입력 응답·문서·인용은 확인 중이며 API 수집값으로 대신 작성하지 않습니다."})


def _executive(slide: Slide, data: DeckData) -> None:
    done = sum(item.score is not None for item in data.assessment.interview_items)
    _replace(slide, {
        4: f"1. System Evidence 26개 중 {len(data.scored)}개 API 판정을 확인했습니다.",
        5: f"(L3 이상 {data.passed}개 · 판정 보류 {len(data.pending)}개 · 조회 범위 내 구성·기록 기준)",
        6: f"2. 수동 인터뷰 54개 중 {done}개 응답이 입력되었습니다.",
        7: "(미입력 영역은 프로세스 부재·과대 응답으로 판정하지 않습니다.)",
        8: "3. 시스템 설정과 실제 운영·업무 성과는 구분해 검증해야 합니다.",
        9: "(사업 목표·고객 VOC·출시 일정·성과 원천은 별도 확인 대상입니다.)",
        10: "II. API 관측과 추가 확인 사항",
        11: "1. 생성·환경 구성 : " + data.fact("DM-SY-01"),
        12: "2. 책임·권한 구성 : " + data.fact("OE-SY-16"),
        13: "(계정 비활성은 소유자 퇴사 증명이 아니며 권한 적정성은 업무 대사가 필요합니다.)",
        14: "3. 비용·보안 구성 : " + data.fact("OT-SY-24"),
        16: "1. 미확인 모집단·필드·권한을 보완하고 원천별 범위를 확인합니다.",
        17: "2. 우선순위·역할·성공 기준은 고객과 합의한 뒤 개선안을 검토합니다.",
        18: "(API 구성 충족률이 조직 전체 성숙도나 사업 효과를 보장하지 않습니다.)",
        19: "(본 보고서 '19. Next 과제' 참고)",
    })


def _overall(slide: Slide, data: DeckData, manual: ManualEvidence) -> None:
    areas = list(data.assessment.areas.values())
    interviews = [area.interview for area in areas if area.interview is not None]
    systems = [area.system for area in areas if area.system is not None]
    corrections = [area for area in areas if area.status == "인터뷰-실측 괴리"]
    _replace(slide, {
        23790: story.headline_overview(data),
        5: _number(data.assessment.overall, level=True) + ("*" if data.assessment.overall_status != "6개 영역 집계" else ""),
        6: "실측 기준 잠정 (인터뷰·실측 확인 필요)" if data.assessment.overall_status != "6개 영역 집계" else "종합 수준 (목표 L3.0)",
        8: _number(mean(interviews) if interviews else None, level=True),
        11: _number(mean(systems) if systems else None, level=True),
        12: "System 실측 (26개 항목)",
        14: f"{len(corrections)}개 단계" if interviews else PENDING,
        15: "괴리 보정 단계 (입력 자료 기준)",
        18: _number(mean(manual.raw_scores) if manual.raw_scores else None, level=True),
        21: _number(mean(interviews) if interviews else None, level=True),
        25: _number(data.assessment.overall, level=True),
        23930: data.fact("OT-SY-24") + "\n조회 범위·통화 확인 필요",
        23967: "프로세스·배포 전 평가 원천을 별도로 확인하고 API 구성값과 구분합니다.",
        24008: data.fact("OE-SY-16") + "\n" + data.fact("OE-SY-17"),
        24030: "미입력 영역은 확인 중. System Evidence는 API 구성·기록의 범위 한정 평가입니다.",
    })
    rows = [["Lifecycle 단계", "프로세스 진단", "System 실측", "괴리", "최종 수준"]]
    for prefix, _, korean, english, _ in AREAS:
        area = data.assessment.areas[prefix]
        gap = area.interview - area.system if area.interview is not None and area.system is not None else None
        rows.append([f"{english} ({korean})", _number(area.interview), _number(area.system),
                     _number(gap), _number(area.final)])
    rows.append(["종합", _number(mean(interviews) if interviews else None),
                 _number(mean(systems) if systems else None), "-", _number(data.assessment.overall)])
    _table(slide, 3, rows)
    for identifier in (17, 20, 23, 32, 34):
        _remove(slide, (identifier,))


def _fit_table(slide: Slide, identifier: int, bottom: float, size: float = 9) -> None:
    table_shape = _table_shape(slide, identifier)
    table = table_shape.table
    available = Inches(bottom) - table_shape.top
    if available <= 0:
        raise ValueError("표의 표시 영역이 유효하지 않습니다.")
    for row in table.rows:
        row.height = available // len(table.rows)
        for cell in row.cells:
            cell.margin_top = cell.margin_bottom = Inches(.005)
            cell.margin_left = cell.margin_right = Inches(.025)
            for paragraph in cell.text_frame.paragraphs:
                paragraph.space_before = paragraph.space_after = Pt(0)
                paragraph.line_spacing = 1.0
                for run in paragraph.runs:
                    run.font.size = Pt(min(run.font.size.pt if run.font.size else size, size))


def _manual_pages(slides: list[Slide], data: DeckData, manual: ManualEvidence) -> None:
    from easm_agent.report_pptx import replace_text, shape

    done = sum(item.score is not None for item in data.assessment.interview_items)
    _replace(slides[7], {24053: f"인터뷰 54개 문항 중 {done}개 응답이 입력되었습니다. 문서·시스템·개선 이력의 확인 여부를 반영합니다."})
    rows = [["Lifecycle 단계", "채점 문항", "주 인터뷰 대상", "제출 / 요청 문서"]]
    for _prefix, _, korean, english, _ in AREAS:
        documents = [row for row in manual.documents if row[0] == english]
        submitted = sum(row[2] == "Y" for row in documents)
        known = any(row[2] in ("Y", "N") for row in documents)
        rows.append([f"{english} ({korean})", "9 (3·2·2·2)", "수동 확인",
                     f"{submitted} / {len(documents)}" if known else PENDING])
    rows.append(["합계", "54", "수동 입력", PENDING if not any(row[2] in ("Y", "N") for row in manual.documents)
                 else f"{sum(row[2] == 'Y' for row in manual.documents)} / {len(manual.documents)}"])
    _table(slides[7], 3, rows)
    _replace(slides[7], {22: str(manual.caps.count(2)) + "개 문항" if manual.caps else PENDING,
                         26: str(manual.caps.count(3)) + "개 문항" if manual.caps else PENDING,
                         30: str(manual.caps.count(4)) + "개 문항" if manual.caps else PENDING,
                         34: str(manual.caps.count(5)) + "개 문항" if manual.caps else PENDING})
    _replace(slides[7], {8: PENDING, 9: "인터뷰 인원·그룹 별도 확인",
                         11: PENDING, 12: "세션·시간 별도 확인",
                         14: str(sum(document[2] == "Y" for document in manual.documents))
                         if any(document[2] in ("Y", "N") for document in manual.documents) else PENDING,
                         15: "실제 문서 제출 입력 기준"})
    _manual_note(slides[7])

    identifiers = ((11, 12, 13, 14, 15), (17, 18, 19, 20, 22), (24, 25, 26, 27, 28),
                   (30, 31, 32, 33, 34), (36, 37, 38, 39, 40), (42, 43, 44, 45, 46))
    for (prefix, *_), targets in zip(AREAS, identifiers, strict=True):
        area = data.assessment.areas[prefix]
        for identifier, value in zip(targets, [area.perspectives[kind] for kind in ("PR", "PE", "DA", "TE")] + [area.interview], strict=True):
            target = shape(slides[8], identifier)
            replace_text(target, _number(value))
            target.fill.solid()
            target.fill.fore_color.rgb = RGBColor.from_string(
                "F2F2F2" if value is None else "DDEBF7" if value >= 3 else "FCE4D6"
            )
            target.line.color.rgb = RGBColor.from_string("BFBFBF" if value is None else "7F7F7F")
            for paragraph in target.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.color.rgb = RGBColor.from_string("666666" if value is None else "000000")
    for kind, column_id, right_id in zip(("PR", "PE", "DA", "TE"), (48, 49, 50, 51), (24192, 24196, 24200, 24204), strict=True):
        values = [area.perspectives[kind] for area in data.assessment.areas.values() if area.perspectives[kind] is not None]
        value = mean(values) if values else None
        _replace(slides[8], {column_id: _number(value), right_id: _number(value)})
    _replace(slides[8], {
        24053: "단계·관점 점수는 입력된 문항과 증적 상한으로 계산합니다. 미입력 영역을 0점이나 취약으로 단정하지 않습니다.",
        52: _number(mean([area.interview for area in data.assessment.areas.values() if area.interview is not None])
                    if any(area.interview is not None for area in data.assessment.areas.values()) else None),
        24208: "입력 문항 기준 관점 평균" if done else "관점별 응답 입력 필요",
        24209: "증적 확인·적용 범위와 함께 검토합니다.",
        24212: "단계별 입력 범위", 24217: "운영 절차 증적 확인",
        24213: f"수동 점수 입력 {done}/54개",
        24216: "문항별 증적 상한을 적용합니다. 미입력은 평균에서 제외합니다.",
        24218: "실제 담당자·절차 유무는 수동 증적이 있어야 판단합니다.",
    })
    for identifier in (62, 63, 24194, 24195, 24198, 24199, 24202, 24203):
        target = next((target for target in slides[8].shapes if target.shape_id == identifier), None)
        if target is not None:
            target.width = target.height = 0
    _manual_note(slides[8])

    date = manual.overview.get("진단 기준일")
    requested = len(manual.documents)
    submitted = sum(row[2] == "Y" for row in manual.documents)
    doc_known = any(row[2] in ("Y", "N") for row in manual.documents)

    def valid(document: tuple) -> bool:
        changed = document[3]
        return (document[2] == document[4] == document[5] == "Y"
                and isinstance(date, datetime) and isinstance(changed, datetime)
                and 0 <= (date - changed).days <= 365)

    rows = [["Lifecycle 단계", "요청", "제출", "유효", "문서 증적 확인 문항"]]
    for _prefix, _, korean, english, _ in AREAS:
        documents = [document for document in manual.documents if document[0] == english]
        known = any(document[2] in ("Y", "N") for document in documents)
        rows.append([f"{english} ({korean})", str(len(documents)) if documents else PENDING,
                     str(sum(document[2] == "Y" for document in documents)) if known else PENDING,
                     str(sum(valid(document) for document in documents)) if known else PENDING, PENDING])
    rows.append(["합계", str(requested) if requested else PENDING, str(submitted) if doc_known else PENDING,
                 str(sum(valid(document) for document in manual.documents)) if doc_known else PENDING,
                 "수동 확인"])
    _table(slides[9], 3, rows)
    entered_documents = [document for document in manual.documents if document[2] in ("Y", "N")]
    _table(slides[9], 5, [["확인 문서", "실사 결과", "판정 영향"]] + [
        [document[1], "제출" if document[2] == "Y" else "미제출",
         "유효" if valid(document) else "요건·증적 확인 필요"] for document in entered_documents[:5]
    ] + [[PENDING, PENDING, PENDING]] * max(0, 5 - len(entered_documents[:5])))
    raw_mean = mean(manual.raw_scores) if manual.raw_scores else None
    capped = [min(value, cap) for value, cap in zip(manual.raw_scores, manual.caps, strict=True)]
    lower = sum(value > cap for value, cap in zip(manual.raw_scores, manual.caps, strict=True))
    _replace(slides[9], {
        24053: f"요청 문서 {requested}건, 제출 {submitted}건. 입력된 실사 결과만 반영합니다." if doc_known else "문서 실사 결과는 입력 후 표시합니다. 원본 예시의 제출·유효·개정 여부를 실제 결과로 사용하지 않습니다.",
        9: _number(raw_mean, level=True), 12: _number(mean(capped) if capped else None, level=True),
        17: f"{lower}개 문항 증적 상한 적용" if capped else PENDING,
        23: f"제출 문서 {submitted}건" if doc_known else "제출 여부 확인 중",
        24: "작성·개정일, 승인·적용 범위로 검토", 25: "입력 증적 기준으로 판단",
    })
    for identifier in (8, 11):
        _bar(slides[9], identifier, None)
    _manual_note(slides[9])

    for page, offset in ((10, 0), (11, 6)):
        _replace(slides[page], {24053: "단계별 실제 인터뷰 기록을 표시합니다. 인용·시사점·조치 방향이 없으면 확인 중으로 남깁니다."})
        for index, (score_id, role1, quote1, role2, quote2, insight, action) in enumerate((
            (7, 9, 10, 12, 13, 15, 16), (19, 22, 23, 25, 26, 28, 29), (32, 34, 35, 37, 38, 40, 41),
        )):
            records = manual.interviews[offset + index * 2:offset + index * 2 + 2]
            phase = AREAS[(0 if page == 10 else 3) + index][0]
            area = data.assessment.areas[phase]
            first = records[0] if records else ("",) * 6
            second = records[1] if len(records) > 1 else ("",) * 6
            _replace(slides[page], {
                score_id: _number(area.interview, level=True),
                role1: first[1] or PENDING, quote1: first[2] or PENDING,
                role2: second[1] or PENDING, quote2: second[2] or PENDING,
                insight: first[4] or second[4] or PENDING, action: first[5] or second[5] or PENDING,
            })


def _scope_pages(slides: list[Slide], data: DeckData) -> None:
    _replace(slides[4], {
        7: "생명주기 6단계 × 4관점\n수동 평가 54문항", 8: "System Evidence 26개 API 구성·기록\n5개 분석 유형",
        10: "인터뷰·문서 실사 수동 입력 자료 기준", 11: "Azure·Graph 읽기 전용 조회와 별도 승인 관리자 증적",
        14: "L1=0%, L2<80%, L3<90%, L4<100%, L5=100%\n조회 실패·필수 값 미확인은 확인 중",
        17: "항목·단계·유형별 API 충족률, 분자·분모·증적",
        24610: "임시 라이선스 발급·권한 변경을 실행한 것으로 표시하지 않습니다. API 평가는 전사 성숙도·실효성과 구분합니다.",
    })
    _replace(slides[12], {
        8: "- System Evidence 26개 API 구성·기록 수집·분석 -",
        9: "9. System 데이터 수집 범위 및 방법\n10. Lifecycle 단계별 System 실측 수준\n11. System Evidence 26개 항목별 판정 결과\n12~15. 상세 분석",
    })
    groups = data.groups()
    _replace(slides[13], {
        24053: story.method_texts(data)[24053],
        24128: "I. 26개 항목 5개 분석 유형",
        4: " - 실제 관측 API 범위", 6: " - " + (data.collected_label() or PENDING),
        8: " - 읽기 전용·별도 승인 증적", 10: " - 마스킹 원천 JSON·분자·분모",
        12: " - 발급·보유 여부 별도 확인",
        24344: "L1 Initial\n확인된 충족률 0%",
        24379: "L2 Managed\n0% 초과~80% 미만",
        24415: "L3 Defined\n80% 이상~90% 미만",
        24452: "L4 Governed\n90% 이상~100% 미만",
        24490: "L5 Optimized\nAPI 충족률 100%",
        24529: "API·별도 승인 읽기 증적 기준. 미지원 플랫폼을 수집한 것으로 표시하지 않습니다.",
        24569: "수동 응답과 API 실측을 구분하며, 미입력·미확인 항목은 0점으로 환산하지 않습니다.",
        24610: FOOTNOTE,
    })
    _table(slides[13], 21, [["분석 유형", "확인 내용", "항목 수"]] + [
        [key + " " + label, "API 구성·기록", str(len(codes))] for key, label, codes in groups
    ])
    collection = data.collection
    counts = (
        [sum(agent.platform == platform for agent in collection.copilot_agents)
         if collection.facts.get("copilot_inventory_complete") is True else None
         for platform in ("copilot_studio", "agent_builder")]
        + [len([agent for agent in collection.agents if agent.platform == "foundry"])
           if collection.facts.get("agent_inventory_complete") is True else None]
        if collection else [None] * 3
    )
    rows = [["플랫폼", "관측 Agent·후보", "수집 방식", "항목 분해"]]
    for index, name in enumerate(("Copilot Studio", "Agent Builder", "Foundry")):
        rows.append([name, str(counts[index]) if counts[index] is not None else PENDING,
                     "승인 위임 읽기" if index < 2 else "진단 SP 읽기", PENDING])
    external_total = 0
    external_complete = not collection or not collection.facts.get("agent365_requested")
    for name, provider in (("ChatGPT Enterprise", None), ("Amazon Bedrock", "AmazonBedrock"),
                           ("Snowflake Cortex", "SnowflakeAI"), ("Claude Enterprise", None)):
        if provider and collection and collection.facts.get("agent365_registry_complete") is True:
            packages = [package for package in collection.agent365_packages if package.platform == provider]
            external_total += len(packages)
            external_complete = True
            rows.append([name, str(len(packages)), "Agent 365 API", "항목별 원천 조건"])
        else:
            rows.append([name, PENDING, "미지원·별도 원천 필요", PENDING])
    rows.append(["통합 관측 합계", str(sum(counts) + external_total)
                 if all(value is not None for value in counts) and external_complete else PENDING,
                 "전사 전체 수가 아님", "API 26개"])
    _table(slides[14], 12, rows)
    _table(slides[14], 16, [["코드·항목", "관측 범위", "측정 상태·한계", "정보 확인"]] + [
        [item.code + " " + story.topic(data, item.code), item.metric or PENDING,
         "API 분모별 확인", "확인" if item.score is not None else PENDING]
        for item in list(data.items.values())[:7]
    ])
    _replace(slides[14], {
        24053: "플랫폼별 관측 목록과 26개 API 평가를 구분합니다. 환경·프로젝트·리소스·금액 분모를 전사 Agent 커버리지로 합산하지 않습니다.",
        44580: "III. 항목별 측정 범위 예시 (전체 26개는 다음 판정 표)",
        44596: f"판정 확인 {len(data.scored)}개\n필수 정보 확인 범위의 API 판정",
        44604: f"판정 보류 {len(data.pending)}개\n권한·필드·분모 확인 필요",
        44613: "전사 커버리지 확인 중\n플랫폼별 적용 범위 별도",
        44624: "미관측·실패·빈 분모는 확인 중입니다.\n운영자 설명은 API 원천을 대체하지 않습니다.\nAPI 구성 존재로 정책 실효성·승인·자동 집행을 추론하지 않습니다.",
        24610: FOOTNOTE,
    })


def _system_pages(slides: list[Slide], data: DeckData) -> None:
    from easm_agent.report_pptx import replace_text, shape

    slide = slides[15]
    _replace(slide, {24652: f"System Evidence 26개 중 {len(data.scored)}개 API 판정을 확인했습니다. 인터뷰 입력 여부와 구분하며 전사 성숙도·정책 실효성을 단정하지 않습니다.",
                     6: f"API 판정 {len(data.scored)}/26개",
                     7: "미확인 항목은 평균에서 제외", 8: "구성·기록 범위만 평가", 28602: FOOTNOTE})
    for area, bar_id, label_id, info_id in zip(
        data.assessment.areas.values(), (25460, 25640, 25829, 26027, 26234, 26450),
        (25519, 25702, 25894, 26095, 26305, 2),
        (44223, 44234, 44246, 44259, 44273, 44288), strict=True,
    ):
        _bar(slide, bar_id, area.system, top=True)
        target = shape(slide, label_id)
        replace_text(target, _number(area.system))
        if area.system is not None:
            target.top = shape(slide, bar_id).top - Inches(0.25)
        _replace(slide, {info_id: f"{area.system_scored}/{area.system_total}개 확인"})
    _remove(slide, (44223, 44234, 44246, 44259, 44273, 44288))
    for (key, label, codes), label_id, score_id in zip(
        data.groups(), (27070, 27319, 27577, 27844, 28120), (27152, 27404, 27665, 4, 28214), strict=True,
    ):
        _replace(slide, {label_id: key + " " + label, score_id: _number(data.average(codes), level=True)})
    rows = [["Lifecycle 단계", "API 실측", "최저 판정 항목", "관측값·범위"]]
    for prefix, _, korean, english, _ in AREAS:
        items = [item for item in data.scored if item.area == prefix]
        lowest = min(items, key=lambda item: (item.score, item.code)) if items else None
        rows.append([f"{english} ({korean})", _number(data.assessment.areas[prefix].system),
                     story.topic(data, lowest.code) if lowest else PENDING,
                     ((lowest.metric or PENDING) + " (" + data.level(lowest.code) + ")") if lowest else PENDING])
    _table(slide, 3, rows)

    slide = slides[16]
    table = _table_shape(slide, 3).table
    while len(table.rows) < 14:
        table._tbl.append(deepcopy(table.rows[len(table.rows) - 1]._tr))
    total_height = sum(row.height for row in list(table.rows)[:11])
    for row in table.rows:
        row.height = total_height // 14
    records = list(data.items.values())
    rows = [["코드·항목", "실측", "판정", "코드·항목", "실측", "판정"]]
    for index in range(13):
        values = []
        for item in (records[index], records[index + 13]):
            values.extend([item.code + " " + story.topic(data, item.code),
                           item.metric or PENDING, f"L{item.score}" if item.score is not None else PENDING])
        rows.append(values)
    _table(slide, 3, rows)
    buckets = story.distribution(data)
    for label, value in zip((28662, 28701, 28749, 28786, 28849), buckets, strict=True):
        _replace(slide, {label: f"{value}개"})
    for identifier in (28651, 28687, 28732, 44321, 44358, 44421, 44493):
        target = next((target for target in slide.shapes if target.shape_id == identifier), None)
        if target is not None:
            target.width = target.height = 0
    _replace(slide, {
        28603: story.headline_matrix(data), 28605: "11. System Evidence 26개 항목별 판정 결과",
        28872: f"API 구성·기록 평가\n확인 {len(data.scored)}개 · 보류 {len(data.pending)}개\n정책 실효성·조직 전체 성숙도와 구분",
        44339: "확인", 44378: f"{len(data.scored)}개",
        44399: "보류", 44444: f"{len(data.pending)}개",
        44468: "전사 범위", 44519: PENDING, 44546: "API 분모별 원천·범위 확인", 28896: FOOTNOTE,
    })


def _cross_and_business(slides: list[Slide], data: DeckData) -> None:
    slide = slides[22]
    for area, system_id, interview_id, final_id in zip(
        data.assessment.areas.values(), (18, 26, 33, 40, 47, 54),
        (19, 27, 34, 41, 48, 55), (20, 28, 35, 42, 49, 56), strict=True,
    ):
        _replace(slide, {system_id: _number(area.system), interview_id: _number(area.interview),
                         final_id: _number(area.final)})
    # Original example bars are not valid for arbitrary manual scores.
    for target in slide.shapes:
        if (not target.has_text_frame or not target.text.strip()) and not target.has_table and Inches(2.1) <= target.top <= Inches(4.1):
            target.width = target.height = 0
    _remove(slide, (5, 6, 7, 8, 9, 10, 11, 12, 57, 59))
    _replace(slide, {58: "프로세스 진단", 60: "System 실측"})
    from easm_agent.report_pptx import shape

    shape(slide, 58).left, shape(slide, 58).width = Inches(2), Inches(1.7)
    shape(slide, 60).left, shape(slide, 60).width = Inches(4), Inches(1.7)
    for system_id, interview_id in zip((18, 26, 33, 40, 47, 54), (19, 27, 34, 41, 48, 55), strict=True):
        shape(slide, system_id).left, shape(slide, system_id).width = Inches(4), Inches(1.7)
        shape(slide, interview_id).left, shape(slide, interview_id).width = Inches(2), Inches(1.7)
    corrections = sum(area.status == "인터뷰-실측 괴리" for area in data.assessment.areas.values())
    manual = sum(item.score is not None for item in data.assessment.interview_items)
    _replace(slide, {
        24053: "수동 프로세스 점수와 API 구성·기록 점수를 구분하여 대조합니다. 미입력 영역은 비교·보정을 확정하지 않습니다.",
        62: f"괴리 보정 {corrections}개 단계" if manual else "수동 응답 입력 후 대조",
        63: "실제 입력 자료와 API 분모 차이를 검토합니다.", 24193: "원천 범위 일치 여부",
        24194: "서로 다른 모집단·기간의 수치를 직접 비교하지 않습니다.",
        24199: f"수동 응답 확인 {manual}/54개", 24200: "API 증적과 수동 자료를 함께 검토",
        24610: "확인되지 않은 수동 응답·증적은 0점이나 과대 응답으로 판정하지 않습니다.",
    })
    rows = [["단계", "수동 입력", "API 관측", "대조 상태"]]
    for prefix, _, korean, _, _ in AREAS[:5]:
        area = data.assessment.areas[prefix]
        related = [item for item in data.items.values() if item.area == prefix]
        rows.append([korean, _number(area.interview), _number(area.system),
                     "입력 범위 검토" if area.interview is not None and related else PENDING])
    _table(slide, 24203, rows)

    _replace(slides[2], {
        5: "고객의 AX 목표·사업 일정·생산성 목표는 별도 승인 자료가 있어야 기재할 수 있습니다. 본 보고서는 관측된 API 구성과 입력된 수동 증적을 구분합니다.",
        13: "II. 고객 사업 목표와 확산 조건 (별도 확인 필요)",
        16: "정량 생산성 목표 " + PENDING, 18: "신규 서비스·출시 일정 " + PENDING,
        21: "제작 참여자·전사 Agent 목표 " + PENDING, 7: "사업 목표·성과·출시 일정은 API가 수집한 지표가 아닙니다.",
    })
    _replace(slides[3], {
        5: "현안과 고객의 목소리는 실제 인터뷰·사업 자료를 입력한 뒤 확정합니다. API 구성만으로 비용 급증·출시 보류·성과 미달을 단정하지 않습니다.",
        8: PENDING, 9: "제작 참여 직원 수 확인 필요", 10: "관측 범위 한정",
        11: "전체 플랫폼 수 별도 확인", 12: PENDING, 13: "생산성 개선율 확인 필요",
        17: "고객 보안·출시 관련 인터뷰 " + PENDING,
        21: "비용 증가 원인·부서 귀속 관련 인터뷰 " + PENDING,
        24: "투자 성과·의사결정 관련 인터뷰 " + PENDING,
        58: "요청·승인 처리 기간 관련 인터뷰 " + PENDING,
        44805: "프로세스 54개 수동 문항과 System Evidence 26개를 구분하여 원인을 확인합니다.",
        7: "실제 VOC·사업 성과 원천이 없으면 원본 가상 인용을 사용하지 않습니다.",
    })
    _replace(slides[23], {
        3: "관측된 API 구성·기록에서 개선 검토 대상을 찾되, 사업 영향·원인·기대 효과는 별도 고객 자료와 검증이 필요합니다.",
        46: "고객 보안 VOC " + PENDING, 47: data.fact("BI-SY-10") + "\n" + data.fact("OT-SY-25"),
        51: "출시 재개·사고 감소 효과\n고객 검증 필요",
        53: "고객 비용 VOC " + PENDING, 54: data.fact("OT-SY-24") + "\n" + data.fact("OT-SY-26"),
        58: "비용 절감·예측 효과\n별도 성과 검증",
        60: "고객 투자 성과 VOC " + PENDING, 61: data.fact("BI-SY-13"),
        45249: "투자 대비 효과\n고객 원천 확인 필요",
        45251: "고객 확산 VOC " + PENDING, 45252: data.fact("DM-SY-01") + "\n" + data.fact("BI-SY-08"),
        45256: "전사 확산 목표\n고객 원천 확인 필요",
        45258: "원인과 사업 성과는 API 구성 충족률만으로 확정하지 않습니다.",
        7: "개선 방안은 검토안입니다. 고객 목표·이행·운영 결과를 별도로 검증해야 합니다.",
    })
    _replace(slides[26], {
        3: "Framework 설계·Platform 구축·운영 정착은 고객과 범위·기간·성공 기준을 합의할 검토안입니다. API 구성 충족률이 사업 성과를 보장하지 않습니다.",
        9: "현재 API 관측 " + f"{len(data.scored)}/26개",
        60: pct(data.ratio("OT-SY-24")) if data.ratio("OT-SY-24") is not None else PENDING,
        44161: pct(data.rate("registry.match")) if data.rate("registry.match") is not None else PENDING,
        44162: "고객 협의",
        44166: pct(data.rate("approval.match")) if data.rate("approval.match") is not None else PENDING,
        44167: "고객 협의",
        44171: str(data.value("security.exposure.open")) if data.value("security.exposure.open") is not None else PENDING,
        44172: "고객 협의",
        61: f"{data.l3_min('OT-SY-24'):.0%} 이상" if data.ratio("OT-SY-24") is not None else PENDING,
        44176: "생산성 목표와 실제 절감 시간은\n별도 고객 성과 자료로 확인",
        44178: "신규 서비스와 출시 시점은\n고객 사업 계획으로 확인",
        44181: "비용·성과 원천을 연결한 뒤\n투자 의사결정 자료로 검토",
        7: "표시 목표는 검토안이며 실현 성과가 아닙니다. 기본 API 26개 평가와 별도 사업 증적을 구분합니다.",
        58: "III. 비즈니스 효과 (고객 검증 필요)",
        2: "(관측 범위)", 4: "(범위 협의)", 5: "(범위 협의)", 12: "(별도 검증)",
    })
    for identifier in (46102, 46146, 46284, 46332, 46482, 46534, 46696):
        _bar(slides[26], identifier, None)
    _remove(slides[26], (46191, 46381, 46587, 46752))


def populate_business_deck(slides: list[Slide], data: DeckData, workbook: Path) -> None:
    from easm_agent.report_pptx import (
        build_creation,
        build_identity,
        build_operations,
    )

    if len(slides) != BIZ_SLIDE_COUNT or len(data.items) != 26:
        raise ValueError("Biz 보고서에는 승인된 27장 템플릿과 SY 26개 Excel이 필요합니다.")
    manual = read_manual_evidence(workbook)
    _replace(slides[0], {4: f"{data.customer} AI Agent Governance Readiness 진단",
                         10: data.collected_label() or PENDING,
                         11: data.disclosure or "저장 실측·수동 입력 기준. 미확인 사업 지표는 별도 확인"})
    _executive(slides[1], data)
    _overall(slides[5], data, manual)
    _manual_pages(slides, data, manual)
    _scope_pages(slides, data)
    _system_pages(slides, data)
    build_creation(slides[17], data)
    build_identity(slides[18], data)
    build_operations(slides[20], data)
    from easm_agent.report_pptx import shape

    shape(slides[17], 29092).width = Inches(1.65)
    shape(slides[17], 29124).left = Inches(2.6)
    shape(slides[17], 29157).left = Inches(2.78)
    shape(slides[17], 29157).width = Inches(3)
    _replace(slides[18], {44574: "ID·Agent 모집단별 관측"})
    _table(slides[17], 58, [["API 항목", "충족 / 측정 분모", "L3 하한", "판정"]] + [
        [code, data.fraction(code) or PENDING, f"{data.l3_min(code):.0%}", data.level(code)]
        for code in ("DM-SY-01", "DS-SY-02", "BI-SY-08")
    ])
    _table(slides[20], 64, [["API 항목", "충족 / 측정 분모", "L3 하한", "판정"]] + [
        [code, _measured_text(data, code),
         f"{data.l3_min(code):.0%}", data.level(code)]
        for code in ("OE-SY-18", "OE-SY-22", "OT-SY-24", "OT-SY-26")
    ])
    # The security page has a new box contract; use the same narrative/metric helpers.
    for code, identifiers in zip(story.security_cards(data), (
        (36167, 36182, 36191, 36224, 36201, 36212),
        (36237, 36266, 36282, 36336, 36299, 36317),
        (36356, 36399, 36422, 36497, 36446, 36471),
    ), strict=True):
        card = story.card_texts(data, code)
        _replace(slides[19], dict(zip(identifiers[:4], (card["title"], card["value"], card["detail"], card["target"]), strict=True)))
        for identifier in identifiers[4:]:
            _bar(slides[19], identifier, None)
    rows = story.exposure_rows(data) or story.defender_rows(data) or story.fallback_security_rows(data)
    _table(slides[19], 36, rows)
    _replace(slides[19], {
        36147: story.headline_security(data), 36524: "II. 보안 점검 원천·관측 범위",
        36582: "III. 외부 도구 연결 보호", 3: story.security_box(data)[0],
        4: "구성·기록 범위 한정", 36678: story.security_box(data)[1], 36712: FOOTNOTE,
    })
    _cross_and_business(slides, data)
    _replace(slides[24], {
        40776: "관측값을 바탕으로 개선 우선순위를 검토하며, 이행 범위·기간·성공 기준은 고객과 협의합니다.",
        4: "Phase 1 · 우선 확인", 5: "권한·원천·미확인 값 보완",
        7: "Phase 2 · 구성 개선 검토", 8: "담당·범위·증적 합의",
        10: "Phase 3 · 운영 효과 검증", 11: "고객 지표로 효과 확인",
        42244: _number(data.assessment.overall, level=True),
        42357: "현재 API 평균 (참고)\n후속 목표·기간은 고객 협의",
        41802: "III. 목표 수준 (고객 협의)",
        43666: "개선 범위·기간·목표는 검토안이며 이행 성과를 보장하지 않습니다.",
    })
    _table(slides[24], 3, story.plan_rows(data))
    for identifier in (42132, 42471, 42819, 43176):
        target = next((target for target in slides[24].shapes if target.shape_id == identifier), None)
        if target is not None:
            target.width = target.height = 0
    _remove(slides[24], (42586, 42702, 42937, 43056, 43297, 43419))
    shape(slides[24], 42244).top = Inches(4)
    shape(slides[24], 42357).left = Inches(7.85)
    shape(slides[24], 42357).top = Inches(4.5)
    shape(slides[24], 42357).width = Inches(2.5)
    shape(slides[24], 42357).height = Inches(1)
    _replace(slides[25], {
        40776: "관측된 구성·기록과 미확인 원천을 바탕으로 우선 검토 대상을 제안합니다. 범위·기간·역할은 고객과 별도 합의합니다.",
        8: "증적·운영 영향·우선순위 검토", 9: "우선 대상은 고객 협의 후 확정",
        43904: "역할·책임, 승인·운영 절차와\n측정 기준·증적을 설계합니다.",
        43951: "관측 가능한 API 구성과 증적을 연결하고\n실제 운영 효과를 별도로 검증합니다.",
        44179: "Iteration 범위·기간은 제안이며 자동 배포·역할 변경을 수행한 것이 아닙니다.",
    })
    candidates = sorted(data.scored, key=lambda item: (item.score, item.code))[:5]
    _table(slides[25], 7, [["대상 영역", "관측 근거", "API 수준", "검토 단계"]] + [
        [story.topic(data, item.code), (item.metric or PENDING) + " / " + (data.fraction(item.code) or PENDING), f"L{item.score}", "고객 협의"]
        for item in candidates
    ] + [[PENDING, PENDING, PENDING, "고객 협의"]] * max(0, 5-len(candidates)))
    for page, identifier, bottom, size in (
        (5, 3, 4.93, 9), (7, 3, 4.08, 9), (9, 3, 4.28, 9), (9, 5, 6.56, 8.5),
        (13, 21, 4.09, 9), (14, 12, 4.1, 8.5), (14, 16, 6.65, 8.5),
        (15, 3, 6.65, 8.5), (16, 3, 6.6, 8), (17, 58, 6.2, 9),
        (18, 46, 6.52, 8.5), (19, 36, 6.44, 8.5), (20, 64, 6.2, 8.5),
        (22, 24203, 6.65, 8.5), (24, 3, 6.42, 8.5), (25, 7, 3.38, 8.5),
    ):
        _fit_table(slides[page], identifier, bottom, size)
    for page, slide in enumerate(slides):
        for target in slide.shapes:
            if target.has_text_frame:
                for node in target._element.iter(qn("a:t")):
                    if node.text:
                        node.text = node.text.replace("20개", "26개").replace("OOO", data.name)
        # Side-by-side totals remain 22 numbered content pages; section dividers are unnumbered.
        if page in (1, 6, 12, 21):
            continue
        title = next((target for target in slide.shapes if target.has_text_frame and target.top < Inches(.4)
                      and target.text.strip()), None)
        if title is None and page != 0:
            raise ValueError(f"{page+1}번 슬라이드의 제목 계약이 없습니다.")


def populate_minimal_deck(slides: list[Slide], data: DeckData, workbook: Path) -> None:
    """Keep supplied prose and manual evidence; replace measured and dependent values only."""
    from easm_agent.report_pptx import replace_text, shape
    from easm_agent.report_values import PROCESS, REPORT, build_report_values

    book = load_workbook(workbook)
    try:
        values = build_report_values(book)
        manual = read_manual_evidence(workbook)
        for slide in slides:
            for target in _walk(slide.shapes):
                if target.has_text_frame:
                    text = re.sub(r"20\s*개(?=\s*(?:항목|SY|System))", "26개", target.text)
                    text = text.replace("System Evidence 20개", "System Evidence 26개")
                    if text != target.text:
                        replace_text(target, text.replace("\v", "\n"))
        _replace(slides[0], {
            10: data.collected_label() or PENDING,
            11: "System Evidence만 저장 API 관측으로 갱신. 인터뷰·문서·인용은 제공 Excel 입력 유지.\n"
                "설명·제언·업무 목표는 원문 참고 자료이며 API 검증 결과가 아님. 미관측 값은 확인 중.",
        })
        if data.registry_codes:
            _replace(slides[0], {
                11: "Agent 365 기반 26개 항목\n"
                    "등록부·플랫폼 API 구성·기록 평가\n"
                    "인터뷰·문서: 제공 Excel 입력 유지\n"
                    "실제 실행 성공·보안 효과와 구분",
            })
        if data.name != DEFAULT_CUSTOMER:
            target = shape(slides[0], 4)
            replace_text(target, target.text.replace("OOO", data.name))
        shape(slides[0], 11).height = Inches(1.3)
        _scope_pages(slides, data)
        _system_pages(slides, data)
        for binding in values.bindings:
            _replace(slides[binding.page], {binding.shape: values.display(binding)})
        for index, bar_id in enumerate((25460, 25640, 25829, 26027, 26234, 26450)):
            area = values.areas[AREAS[index][0]]
            if area.system is not None:
                label = shape(slides[15], (25519, 25702, 25894, 26095, 26305, 2)[index])
                bar = shape(slides[15], bar_id)
                label.top = bar.top + bar.height - label.height - Inches(.04)
        shape(slides[16], 44468).width = Inches(1.05)
        shape(slides[16], 44519).left = Inches(9.05)
        shape(slides[16], 44519).width = Inches(1.2)
        _replace(slides[16], {44546: "API 분모별 원천 확인"})
        for page, identifier, cell in (
            (15, 3, "K"), (5, 3, "J"),
        ):
            table = _table_shape(slides[page], identifier).table
            for index in range(6):
                row = index + 5
                if page == 5:
                    for column, source in ((1, "J"), (2, "K"), (3, "L"), (4, "M")):
                        value = values.cells[REPORT, f"{source}{row}"]
                        replace_text(table.cell(index+1, column), _number(value))
                else:
                    replace_text(table.cell(index+1, 1), _number(values.cells[REPORT, f"{cell}{row}"]))
            if page == 5:
                for column, source in ((1, "J"), (2, "K"), (4, "M")):
                    replace_text(table.cell(7, column), _number(values.cells[REPORT, f"{source}11"]))
        final = _number(values.overall, level=True)
        process = _number(values.cells[REPORT, "J11"], level=True)
        system = _number(values.cells[REPORT, "K11"], level=True)
        _replace(slides[1], {
            4: f"1.  AI Agent Governance 종합 수준은 {final} (제공 입력·API 관측 기준)",
            5: f"(프로세스 진단 {process} · System 실측 {system} / API 판정 {len(data.scored)}/26개)",
            6: "2.  수요 · 설계 단계는 제공 인터뷰와 System Evidence를 교차 확인",
            7: f"(인터뷰 대비 실측 1.5점 이상 괴리 보정 : {values.cells[REPORT, 'D20']}개 단계)",
            8: "3.  운영 · 최적화 단계 수준은 제공 입력과 API 관측을 구분",
            9: "(원문 인터뷰 진술은 보존하며, API 구성 존재로 운영 효과를 단정하지 않음)",
            11: "1.  생성 통제 : 승인 모집단·Shadow Agent 실측은 확인 중",
            12: "2.  책임 · 권한 통제 : " + data.fact("OE-SY-16"),
            13: "(계정 비활성을 소유자 퇴사로 단정하지 않음)",
            14: "3.  데이터 · 비용 통제 : " + _measured_text(data, "OT-SY-24"),
        })
        _replace(slides[5], {
            12: "System 실측 (26개 항목)",
            15: "괴리 보정 단계",
            23930: _measured_text(data, "OT-SY-24"),
            23967: "배포 전 평가 모집단\n확인 중",
            24008: data.fact("OE-SY-16"),
        })
        heatmap = ((11, 12, 13, 14, 15), (17, 18, 19, 20, 22), (24, 25, 26, 27, 28),
                   (30, 31, 32, 33, 34), (36, 37, 38, 39, 40), (42, 43, 44, 45, 46))
        for index, identifiers in enumerate(heatmap, 63):
            for identifier, column in zip(identifiers, "FGHIK", strict=True):
                _replace(slides[8], {identifier: _number(values.cells[PROCESS, f"{column}{index}"])})
        for page, offset in ((10, 0), (11, 6)):
            for index, identifiers in enumerate(((7, 9, 10, 12, 13, 15, 16),
                                                 (19, 22, 23, 25, 26, 28, 29),
                                                 (32, 34, 35, 37, 38, 40, 41))):
                first, second = manual.interviews[offset+index*2:offset+index*2+2]
                phase = (0 if page == 10 else 3) + index
                texts = (_number(values.areas[AREAS[phase][0]].interview, level=True),
                         first[1], first[2], second[1], second[2], first[4] or second[4], first[5] or second[5])
                for identifier, text in zip(identifiers, texts, strict=True):
                    target = shape(slides[page], identifier)
                    if target.text.replace("\v", "\n") != (text or PENDING).replace("\v", "\n"):
                        replace_text(target, (text or PENDING).replace("\v", "\n"))
        for page, identifiers in (
            (17, (29337, 29542, 29772, 30027, 30307, 30612, 31081, 31371)),
            (18, (32796, 33369, 33978, 34623, 35188, 44574)),
            (19, (36182, 36266, 36399, 4)),
            (20, (37293, 37548, 37828, 38133, 38463, 38818)),
        ):
            _replace(slides[page], dict.fromkeys(identifiers, PENDING))
        for page, identifiers in (
            (17, (29226, 29299, 29416, 29499, 29631, 29724, 29871, 29974, 30136, 30249,
                  30426, 30549, 31011, 31224, 31297)),
            (19, (36201, 36212, 36299, 36317, 36446, 36471)),
            (20, (37198, 37245, 37443, 37495, 37713, 37770, 38008, 38070, 38328, 38395, 38673, 38745)),
        ):
            _remove(slides[page], identifiers)
        _table(slides[17], 58, [["항목", "실측 결과", "L3 목표 기준", "판정"]] + [
            [code, data.fraction(code) or PENDING, f"{data.l3_min(code):.0%}", data.level(code)]
            for code in ("DM-SY-01", "DS-SY-02", "BI-SY-08")
        ])
        for page, identifier in ((18, 46), (19, 36)):
            table = _table_shape(slides[page], identifier).table
            for row in list(table.rows)[1:]:
                for cell in list(row.cells)[1:]:
                    replace_text(cell, PENDING)
        # "과다 권한 유형" (columns 3-4) reuses the already-measured 2b_세부 내역 role breakdown;
        # "고아 · 미지정 구분" (columns 1-2) stays pending - "소유자 퇴사" needs separate HR data this
        # system does not collect, and partially filling only 2 of its 3 rows would be misleading.
        if "2b_세부 내역" in book.sheetnames:
            detail = book["2b_세부 내역"]
            rows = list(_table_shape(slides[18], 46).table.rows)
            counts: list[float] = []
            for offset, row in zip(range(12, 15), rows[1:4], strict=True):
                label, count = detail[f"A{offset}"].value, detail[f"B{offset}"].value
                if label is not None:
                    replace_text(row.cells[2], str(label))
                if isinstance(count, (int, float)):
                    replace_text(row.cells[3], f"{count:g}")
                    counts.append(count)
            # B16 is itself a formula (not yet recalculated at this point) - sum the real values
            # already read above instead of trusting its cached/formula cell value.
            if len(counts) == 3:
                replace_text(rows[4].cells[3], f"{sum(counts):g}")
        _table(slides[20], 64, [["항목", "실측 결과", "L3 목표 기준", "판정"]] + [
            [code, _measured_text(data, code), f"{data.l3_min(code):.0%}", data.level(code)]
            for code in ("OE-SY-18", "OT-SY-24", "OT-SY-26")
        ])
        # The original horizontal cross-validation axis stops at L4.
        chart = slides[22]
        for level, identifier in enumerate((6, 8, 10, 12), 1):
            label = f"L{level}"
            _replace(chart, {identifier: label})
            shape(chart, identifier).left = Inches(1.98 + (level-1)*.98) - shape(chart, identifier).width//2
            grid = next(s for s in chart.shapes if s.shape_id == identifier-1)
            grid.left = Inches(1.98 + (level-1)*.98)
        fifth = deepcopy(shape(chart, 12)._element)
        fifth.find(qn("p:nvSpPr")).find(qn("p:cNvPr")).set("id", "50001")
        chart.shapes._spTree.append(fifth)
        fifth_shape = shape(chart, 50001)
        replace_text(fifth_shape, "L5")
        fifth_shape.left = Inches(5.9) - fifth_shape.width//2
        for index, triple in enumerate(((15, 16, 17), (23, 24, 25), (30, 31, 32),
                                         (37, 38, 39), (44, 45, 46), (51, 52, 53))):
            line, point_a, point_b = [next(s for s in chart.shapes if s.shape_id == identifier) for identifier in triple]
            row = index + 5
            scores = [values.cells[REPORT, f"{column}{row}"] for column in ("K", "J")]
            if not all(isinstance(value, (int, float)) for value in scores):
                _remove(chart, triple)
            else:
                for point, value in zip((point_a, point_b), scores, strict=True):
                    point.left = Inches(1.98 + (value-1)*.98) - point.width//2
                line.left = min(point_a.left+point_a.width//2, point_b.left+point_b.width//2)
                line.width = abs((point_a.left+point_a.width//2)-(point_b.left+point_b.width//2))
            for kind, (identifier, column) in enumerate(zip(
                ((18, 26, 33, 40, 47, 54)[index], (19, 27, 34, 41, 48, 55)[index]),
                ("K", "J"), strict=True,
            )):
                target = shape(chart, identifier)
                value = values.cells[REPORT, f"{column}{row}"]
                if isinstance(value, (int, float)):
                    target.left = Inches(1.98 + (value-1)*.98) - target.width//2
                    target.top += Inches(.14 if kind else -.04)
        cross = _table_shape(chart, 24203).table
        for index in range(1, len(cross.rows)):
            replace_text(cross.cell(index, 2), "API 단계 수준 상단 참조")
            replace_text(cross.cell(index, 3), "별도 대사")
        cross_shape = _table_shape(chart, 24203)
        for row in cross.rows:
            row.height = (Inches(6.6)-cross_shape.top)//len(cross.rows)
        for page in (17, 18, 19, 20):
            for target in _walk(slides[page].shapes):
                if target.has_text_frame:
                    text = target.text
                    if .55 < target.top/Inches(1) < 7 and re.search(r"\d|[⅓]", text):
                        replace_text(target, PENDING if len(text) < 25 else "해당 상세 지표는 실측 확인 중")
                    if page == 18 and not text.strip() and Inches(2) < target.top < Inches(4.1) and target.height < Inches(.3):
                        target._element.getparent().remove(target._element)
        months = sorted(key.split(".")[2] for key in data.metrics if key.startswith("cost.month.") and key.endswith(".total"))
        currencies = sorted({data.metrics[f"cost.month.{month}.total"].unit for month in months
                             if data.metrics[f"cost.month.{month}.total"].value is not None})
        _replace(slides[20], {37107: "(단위 : " + ("/".join(currencies) or PENDING) + ")"})
        for index, month in enumerate(months[-6:], 6-min(6, len(months))):
            metric = data.metrics[f"cost.month.{month}.total"]
            _replace(slides[20], {
                (37293, 37548, 37828, 38133, 38463, 38818)[index]:
                    f"{metric.value:.2f} {metric.unit}" if metric.value is not None else PENDING,
                (37342, 37602, 37887, 38197, 38532, 38892)[index]: month[:4] + "." + month[4:],
            })
        for page in (5, 23, 24, 26):
            for target in _walk(slides[page].shapes):
                if target.has_text_frame:
                    text = target.text.replace("L2.4", final)
                    if page in (23, 24):
                        text = re.sub(r"실측\s*L[\d.]+[~～]\s*[\d.]+", f"실측 {system}", text)
                        text = re.sub(r"(T3[/·]T4)\s*L[\d.]+", r"\1 API 유형별 수준 참조", text)
                    if text != target.text:
                        replace_text(target, text.replace("\v", "\n"))
        _replace(slides[22], {
            24053: "제공 인터뷰와 API 구성·기록을 교차 확인하며 미관측 값은 보정하지 않습니다.",
            62: f"괴리 보정 : {values.cells[REPORT, 'D20']}개 단계",
            24193: "단계별 관측 범위 확인",
            24194: "인터뷰의 '절차 없음' 진술은 보존.\n고아·비용 식별 상세 실측은 확인 중",
            24199: "제공 진술과 API 관측의\n모집단·평가 의미를 별도 대사",
            24610: "제공 입력과 실측 괴리가 설정 기준 이상이고 필수 신뢰도를 충족할 때만 보정. 미관측은 0점으로 환산하지 않음.",
        })
        _replace(slides[26], dict.fromkeys((60, 44161, 44166, 44171), PENDING))
        _remove(slides[26], (46102, 46284, 46482, 46696))
        _replace(slides[23], {
            47: data.fact("BI-SY-10") + "\n" + data.fact("OT-SY-25"),
            54: _measured_text(data, "OT-SY-24") + "\n" + data.fact("OT-SY-26"),
            61: data.fact("BI-SY-13") + "\n" + data.fact("OE-SY-16"),
            45252: data.fact("DM-SY-01") + "\n" + data.fact("BI-SY-08"),
        })
        candidates = sorted(data.scored, key=lambda item: (item.score, item.code))[:5]
        _table(slides[25], 7, [["대상 영역", "관측 근거", "API 수준", "검토 단계"]] + [
            [story.topic(data, item.code), data.fact(item.code), f"L{item.score}", "고객 협의"]
            for item in candidates
        ] + [[PENDING, PENDING, PENDING, "고객 협의"]] * max(0, 5-len(candidates)))
        _fit_table(slides[25], 7, 3.38, 8.5)
        matrix = _table_shape(slides[16], 3)
        for row in matrix.table.rows:
            row.height = (Inches(6.45)-matrix.top)//len(matrix.table.rows)
            for cell in row.cells:
                cell.margin_top = cell.margin_bottom = Inches(.005)
                for paragraph in cell.text_frame.paragraphs:
                    paragraph.space_before = paragraph.space_after = Pt(0)
                    paragraph.line_spacing = 1.0
    finally:
        book.close()


def business_notes(data: DeckData, page: int) -> str:
    lines = [
        f"[발표 메모] Biz 연결 보고서 {page+1}/27",
        "저장된 API 관측값과 수동 입력 자료만 사용합니다. 미입력 사업 목표·VOC·성과는 확인 중입니다.",
        FOOTNOTE, "", "System Evidence 26개 근거",
    ]
    for code in data.items:
        fraction = data.fraction(code)
        lines.append(code + " " + data.level(code) + (" / " + fraction if fraction else ""))
    refs = sorted({ref for metric in data.metrics.values() for ref in metric.evidence_refs})
    if refs:
        lines.extend(["", "증적 참조", ", ".join(refs)])
    return "\n".join(lines)
