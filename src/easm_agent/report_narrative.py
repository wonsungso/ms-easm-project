"""Slide-by-slide messages for the report deck.

The reader is a non-technical business leader. Slide titles, headings, table headers and labels keep the
approved template's wording (Executive Summary, Lifecycle, L1~L5, CIO/CAIO/CISO ...); only the one-line
conclusions and the explanations are written in everyday words. Settings are translated into business
meaning (never used as sentence subjects), risks are always stated as possibilities, and item codes stay
out of the prose.
"""

from __future__ import annotations

import re

from easm_agent.deck_model import AREAS, CORRECTION_GAP, LEVEL_NAMES, TARGET_LEVEL
from easm_agent.report_story import (
    PENDING_LABEL,
    DeckData,
    em,
    fit,
    pct,
    pick,
)
from easm_agent.report_terms import (
    CARD,
    CARD_TITLE,
    DOMAIN_TERMS,
    DOMAINS,
    FACTS,
    GROUP_FOCUS,
    GROUP_LONG,
    KEY_ROWS,
)

DEFAULT_TOOLS = {
    7: ("Agent 365", "Power Platform", "Foundry", "Entra"),
    8: ("Entra", "Foundry"),
    9: ("Foundry", "Azure Policy", "Defender for Cloud"),
    10: ("Azure Monitor", "Cost Management", "Agent 365"),
}
TOOL_SHORT = {"Microsoft Entra": "Entra", "Microsoft Foundry": "Foundry"}
CONTROL_QUESTIONS = (
    ("creation", "생성", "누가 만드는가"),
    ("identity", "책임", "누가 책임지는가"),
    ("security", "접근", "무엇에 접근하는가"),
)
CONTROL_RISK = {"creation": "업무 데이터 유출", "identity": "책임 추적 불가", "security": "무단 접근"}
DOMAIN_CODES = {key: codes for key, _short, _title, codes in DOMAINS}
HEADLINE_IDS = {
    1: (43672,), 2: (23790,), 3: (24053,), 4: (24652,), 5: (28603,), 6: (28921,), 7: (31839,),
    8: (36147,), 9: (36747,), 10: (40776,), 11: (40776,),
}
ALL_CODES = tuple(code for codes in DOMAIN_CODES.values() for code in codes)
NOTE_CODES = {
    1: ALL_CODES, 2: ALL_CODES, 4: ALL_CODES, 5: ALL_CODES,
    6: DOMAIN_CODES["creation"], 7: ("DP-SY-15", "OE-SY-16", "DS-SY-03", "OE-SY-17", "OE-SY-19"),
    8: ("BI-SY-09", "BI-SY-10", "BI-SY-11", "BI-SY-14", "DS-SY-05", "DS-SY-06", "DS-SY-07", "OT-SY-25"),
    9: ("OE-SY-18", "OE-SY-20", "OE-SY-21", "OE-SY-22", "OT-SY-23", "OT-SY-24", "OT-SY-26"),
    10: ALL_CODES, 11: ALL_CODES,
}
NOTE_PREFIXES = {
    0: ("inventory.", "scope."),
    1: ("approval.", "registry.", "security.exposure", "business."),
    2: ("approval.", "registry.", "evaluation.", "copilot.owner_missing", "business."),
    3: ("inventory.", "scope.", "criteria.", "group."),
    6: ("creation.", "approval.", "registry."),
    7: ("identity.", "copilot.owner_missing"),
    8: ("evaluation.", "security."),
    9: ("cost.", "usage.", "audit.", "business.", "catalog.usage."),
    10: ("business.",),
    11: ("business.",),
}
OPS_BARS = ("OE-SY-18", "OE-SY-20", "OE-SY-21", "OE-SY-22", "OT-SY-26", "OT-SY-24")
OPS_NAMES = {"OE-SY-18": "기록 저장", "OE-SY-20": "이상 알림", "OE-SY-21": "알림 담당",
             "OE-SY-22": "지역·보존 정보", "OT-SY-26": "예산 알림", "OT-SY-24": "비용 구분"}
OPS_ROW_NAMES = {"OE-SY-18": "실행 기록 저장", "OE-SY-22": "지역·보존 정보", "OT-SY-24": "Agent별 비용 구분",
                 "OT-SY-26": "예산 초과 알림"}
IDENTITY_BARS = ("DP-SY-15", "OE-SY-16", "DS-SY-03", "OE-SY-17", "OE-SY-19")
IDENTITY_NAMES = {
    "DP-SY-15": "에이전트 청사진 연결\n(DP-SY-15)", "OE-SY-16": "소유자·스폰서 지정\n(OE-SY-16)",
    "DS-SY-03": "ID 청사진 연결\n(DS-SY-03)", "OE-SY-17": "과도한 권한 없음\n(OE-SY-17)",
    "OE-SY-19": "플랫폼별 인증·권한 구성\n(OE-SY-19)",
}
IDENTITY_TITLE = {
    "DP-SY-15": "청사진에 연결되지 않은 에이전트가 있다", "OE-SY-16": "담당자 공백이 있다",
    "DS-SY-03": "청사진에 연결되지 않은 에이전트 ID가 있다", "OE-SY-17": "과도한 권한이 열려 있다",
    "OE-SY-19": "플랫폼별 인증·권한 구성을 검토해야 한다", "CA": "ID는 있으나 접속 조건 제한이 없다",
}
IDENTITY_ACTION = {
    "DP-SY-15": "미연결 에이전트의 청사진 연결 검토", "OE-SY-16": "스폰서 미지정 ID 보완",
    "DS-SY-03": "에이전트 ID를 청사진에 연결", "OE-SY-17": "불필요한 권한 회수",
    "OE-SY-19": "플랫폼별 인증·권한 구성 검토", "CA": "접속 조건 제한 규칙 적용 결정",
}
RECOMMEND = {
    "DP-SY-15": "미연결 에이전트 청사진 연결 검토", "OE-SY-16": "스폰서 미지정 ID 보완",
    "DS-SY-03": "에이전트 ID 연결 정리", "OE-SY-17": "과도한 권한 회수",
    "OE-SY-19": "플랫폼별 인증·권한 구성 검토", "CA": "접속 조건 제한 규칙 적용",
}
RISK_SHORT = {
    "DS-SY-02": "정보 유출 가능성", "BI-SY-08": "관리자 통제 약함", "DM-SY-01": "제작 권한 적정성 미확인",
    "DP-SY-15": "일괄 관리 어려움", "OE-SY-16": "책임 공백 가능성", "DS-SY-05": "인터넷 접근 시도 가능",
    "BI-SY-14": "규칙 위반 방치 가능성", "OE-SY-18": "원인 추적 어려움", "OE-SY-22": "기록 조기 소실 가능성",
    "OT-SY-24": "비용 통제 어려움", "CA": "ID 탈취 시 악용 가능성", "OE-SY-17": "권한 오남용 가능성",
}
TOPIC = {
    "DM-SY-01": "역할 할당 확인 환경", "DS-SY-02": "업무 데이터 유출 방지", "DS-SY-03": "에이전트 ID 청사진 연결",
    "DS-SY-04": "모델 구성", "DS-SY-05": "접근 범위 구성", "DS-SY-06": "도구 승인·동의",
    "DS-SY-07": "암호화 연결", "BI-SY-08": "관리자 보호 설정", "BI-SY-09": "완료 평가 기록",
    "BI-SY-10": "보안 구성 점검", "BI-SY-11": "응답 안전 필터", "BI-SY-12": "버전·게시 기록",
    "BI-SY-13": "담당자 정보", "BI-SY-14": "회사 규칙 준수", "DP-SY-15": "에이전트 청사진 연결",
    "OE-SY-16": "담당자 지정", "OE-SY-17": "권한 범위", "OE-SY-18": "실행 기록 저장",
    "OE-SY-19": "인증·권한 구성", "OE-SY-20": "이상 알림", "OE-SY-21": "알림 담당 지정",
    "OE-SY-22": "지역·보존 정보", "OT-SY-23": "사용량 확인", "OT-SY-24": "비용 구분",
    "OT-SY-25": "보안 점검 서비스", "OT-SY-26": "예산 알림",
}
SECURITY_POOL = ("BI-SY-10", "BI-SY-11", "BI-SY-14", "DS-SY-05", "OT-SY-25")
CONTROL_VERDICT = {
    "충족": "를 충족", "근접했으나 미달": "에 근접했으나 미달", "미달": "에 미달",
}


def topic(d: DeckData, code: str) -> str:
    return d.label(code) if code in d.registry_codes else TOPIC.get(code, d.label(code))


def compact(d: DeckData, code: str) -> str:
    """Short business label with the n/d numbers, e.g. '유출 방지 규칙 적용 0/2'."""
    if d.score(code) is None or code in d.registry_codes:
        return d.fact(code)
    pair = d.counts(code)
    if pair is None or code not in FACTS:
        return d.fact(code)
    if d.currency(code):
        return d.fact(code)
    return FACTS[code][1].split(" {d}")[0] + f" {pair[0]:g}/{pair[1]:g}"


def risk_short(d: DeckData, code: str) -> str:
    if code in d.registry_codes:
        return d.risk(code)
    return RISK_SHORT.get(code) or d.risk(code)


def tool_names(d: DeckData, page: int) -> list[str]:
    wanted = DEFAULT_TOOLS.get(page)
    if d.tools is None:
        return list(wanted or ())
    names = [TOOL_SHORT.get(name, name) for name in d.tools]
    return [name for name in names if wanted is None or name in wanted]


def footer(d: DeckData, page: int, *notes: str, lead: str = "", limit: float = 88) -> str:
    """First footnote line: notes first, then as many collection tools as fit."""
    head = ", ".join(note for note in notes if note)
    head = lead if not head else f"{lead}     ※ {head}" if lead else f"※ {head}"
    tools = tool_names(d, page)
    for count in range(len(tools), 0, -1):
        text = "     ".join(part for part in (head, "※ 수집 도구 : " + " · ".join(tools[:count])) if part)
        if em(text) <= limit:
            return text
    return head or ("※ 수집 도구 : " + tools[0] if tools else "")


def pending_names(d: DeckData) -> str:
    return " · ".join(topic(d, item.code) for item in d.pending)


def pending_reasons(d: DeckData) -> str:
    reasons = []
    for item in d.pending:
        plain = d.pending_reason(item.code)
        if plain not in reasons:
            reasons.append(plain)
    return " · ".join(reasons)


def catalog_clause(d: DeckData) -> str | None:
    catalog = d.catalog
    if catalog is None:
        return None
    if catalog.source == "통합 관측 생성월":
        return f"생성 시각이 확인된 통합 관측 대상이 월 {catalog.first}개 → {catalog.last}개로"
    word = ("Agent 365 목록 패키지" if catalog.source.startswith("Agent 365") else "신규 Azure 에이전트")
    store = "(스토어 앱 포함)" if catalog.source.startswith("Agent 365") else ""
    base = f"{word}가 월 {catalog.first}개 → {catalog.last}개{store}로"
    return base + (" 빠르게 늘고 있고" if catalog.last > catalog.first else " 이어지고 있고")


def control_state(d: DeckData, codes: tuple[str, ...]) -> tuple[str, str | None]:
    """The single verdict behind slides 2 and 3: gap (below L3), partial (L3 met, some left), pending or met."""
    gap = d.worst_gap(codes)
    if gap is not None:
        return "gap", gap
    partial = sorted((c for c in codes if c in d.items and d.score(c) is not None and d.counts(c)
                      and d.counts(c)[0] < d.counts(c)[1]),
                     key=lambda c: (d.ratio(c) or 0, codes.index(c)))
    if partial:
        return "partial", partial[0]
    waiting = [c for c in codes if c in d.items and d.score(c) is None]
    if waiting:
        return "pending", waiting[0]
    return "met", None


def control_line(d: DeckData, key: str, limit: float) -> str:
    state, code = control_state(d, DOMAIN_CODES[key])
    if state == "gap":
        return pick([f"{d.fact(code)} → {risk_short(d, code)}", d.fact(code)], limit)
    if state == "partial":
        return pick([f"목표(L3) 충족, {d.fact(code)} - 나머지 보완 필요", f"목표 충족 · {d.fact(code)}"], limit)
    if state == "pending":
        return d.fact(code)
    return "목표(L3) 충족"


# ---- slide 2 ---------------------------------------------------------------------------------
def divergence(d: DeckData) -> tuple[str, str]:
    corrected = d.corrected()
    if corrected:
        names = " · ".join(d.area_name(p) for p in corrected[:3])
        return (
            pick([f"2.  {names} 단계 : '통제한다'는 응답과 실제 시스템 설정이 달라 점수를 낮춰 보정",
                  f"2.  {names} 단계는 응답과 실제 설정이 달라 점수를 낮춰 보정"], 48),
            f"     (인터뷰가 System Evidence보다 {CORRECTION_GAP:g}점 이상 높으면 System Evidence 점수 + 1.0으로 보정)",
        )
    ahead = d.ahead()
    if ahead:
        names = " · ".join(d.area_name(p) for p, _gap in ahead[:2])
        weak = d.weakest_perspective([p for p, _gap in ahead])
        top = ahead[0][1]
        hint = f"{weak} 쪽 응답이 낮음" if weak else "인터뷰 응답이 낮음"
        return (
            pick([f"2.  {names} 단계 : 인터뷰 응답이 System Evidence보다 낮아 업무 절차·인식 정착 확인 필요",
                  f"2.  {names} 단계는 업무 절차·인식 정착 확인 필요"], 56),
            pick([f"     ({hint}, System Evidence보다 최대 {top:.1f}점 낮음 - 최종 점수는 낮은 쪽인 인터뷰 기준)",
                  f"     (System Evidence보다 최대 {top:.1f}점 낮아 최종 점수는 인터뷰 기준)"], 54),
        )
    return (
        "2.  인터뷰 응답과 System Evidence 결과가 대체로 일치 (단계별 차이 1.0점 미만)",
        "     (보정 없음 - 응답과 실제 설정이 서로 뒷받침)",
    )


def summary(d: DeckData) -> dict[int, str]:
    phrase = {"충족": "목표(L3)를 충족", "근접했으나 미달": "목표(L3)에 근접했으나 미달",
              "미달": "목표(L3)에 미달"}.get(d.target_gap)
    if phrase:
        first = "1.  " + pick([
            f"{d.name}의 AI 에이전트 관리 수준은 {d.overall_label}로 {phrase}",
            f"AI 에이전트 관리 수준은 {d.overall_label}로 {phrase}",
        ], 48)
    else:
        first = "1.  AI 에이전트 관리 수준은 확인 중"
    parts = ["AI 에이전트 : 업무를 대신 수행하는 AI", f"측정 {len(d.scored)}개 항목 중 L3 충족 {d.passed}개"]
    if d.pending:
        parts.append(f"{len(d.pending)}개 확인 중")
    sub = "     (" + fit(parts, 50, sep=" · ") + ")"
    div_first, div_sub = divergence(d)
    tasks = [t for t in d.tasks() if t["phase"] == 1][:3]
    immediate = fit([str(t["short"]) for t in tasks], 30, sep=" · ")
    domains = d.domains()
    names = [str(row["short"]).replace(" · ", "·") for row in domains]
    later = " · ".join(names[2:5])
    gap = d.worst_gap(DOMAIN_CODES["identity"])
    pair = d.counts("DP-SY-15")
    if pair and pair[1] > pair[0]:
        missing = pair[1] - pair[0]
        identity_sub = pick([
            f"(에이전트 ID 청사진에 연결되지 않은 에이전트 {missing:g}개 - 소유자·권한 기본값을 일괄 적용하기 어려울 수 있음)",
            f"(청사진에 연결되지 않은 에이전트 {missing:g}개 - 일괄 관리가 어려울 수 있음)",
        ], 62)
    elif gap:
        identity_sub = f"({d.long_fact(gap)} - {d.risk(gap)})"
    else:
        identity_sub = "(청사진 연결·담당자 지정이 목표를 충족 - 신규 에이전트에도 같은 기준 적용 필요)"
    return {
        43672: first + "\n" + sub,
        43676: div_first + "\n" + div_sub,
        43687: "1.  생성 통제 : " + control_line(d, "creation", 44),
        43694: "2.  책임 · 권한 통제 : " + control_line(d, "identity", 44) + "\n     "
               + pick([identity_sub, identity_sub[:48] + ")"], 62),
        43702: "3.  접근 통제 : " + control_line(d, "security", 44),
        43721: "1.  즉시(30일) : " + (f"{immediate} 등으로 위험 확산 차단" if immediate
                                     else "확인된 공백 없음 - 현 수준 유지 · 정기 점검"),
        43732: "2.  가장 취약한 운영통제 영역부터 Framework 설계 · Platform 구축을 단계적 반복 추진\n"
               + (f"     (Iteration 1 : {', '.join(names[:2])} 통제"
                  + (f" → 이후 {later} 영역으로 확대)" if later else ")"))
               + "\n     ( 본 보고서 10장 참고 )",
        43744: footer(d, 0, limit=88) or "※ 수집 도구 : Azure · Microsoft 365 관리 도구 (읽기 전용)",
    }


# ---- slide 3 ---------------------------------------------------------------------------------
def gap_risks(d: DeckData) -> list[str]:
    return [CONTROL_RISK[key] for key, *_ in CONTROL_QUESTIONS if d.gaps(DOMAIN_CODES[key])
            and key != "identity"] + (["책임 추적 불가"] if d.gaps(DOMAIN_CODES["identity"]) else [])


def headline_overview(d: DeckData) -> str:
    growth = catalog_clause(d)
    risks = gap_risks(d)
    verdict = CONTROL_VERDICT.get(d.target_gap)
    catalog = d.catalog
    built = ""
    if catalog is not None and catalog.source.startswith("Agent 365") and catalog.total:
        built = f", 직접 제작·구성 {catalog.built}개"
    level = f"AI 에이전트 관리 수준은 {d.overall_label}로 목표(L3){verdict}" if verdict else "AI 에이전트 관리 수준은 확인 중"
    tail = (f" - {' · '.join(risks)} 가능성이 핵심 위험" if risks
            else " - 구성 통제는 기준을 충족하나 확대 시 유지 점검이 과제")
    options = []
    if growth:
        who = f"{d.name}의 "
        with_built = growth.replace("(스토어 앱 포함)", f"(스토어 앱 포함{built})") if built else growth
        options += [who + with_built + " " + level + tail, who + growth + " " + level + tail]
    options.append(f"{d.name}의 {level}{tail}")
    return pick(options, 112)


def row_status(d: DeckData, codes: tuple[str, ...]) -> str:
    state, _code = control_state(d, codes)
    if d.worst(codes) is None:
        return "확인 중"
    return {"gap": "미흡", "partial": "목표 충족 · 보완 필요", "pending": "일부 확인 중", "met": "양호"}[state]


def key_rows(d: DeckData) -> list[list[str]]:
    rows = [["핵심 발견", "근거 데이터 (실측)", "비즈니스 영향"]]
    for index, (label, codes, good) in enumerate(KEY_ROWS, 1):
        status = row_status(d, codes)
        state, code = control_state(d, codes)
        parts = d.evidence(codes, 2)
        if index == 3 and d.conditional_access:
            applied, total = d.conditional_access
            parts.append(f"ID 접속 조건 제한 {total}개 중 {applied}개")
        if state == "gap":
            impact = d.risk(code)
        elif state == "partial":
            impact = "목표(80%) 충족, 나머지는 보완 필요"
        elif state == "met":
            impact = good
        else:
            impact = "확인 중인 항목은 결과에 따라 위험 판단"
        if index == 3 and d.conditional_access and d.conditional_access[0] == 0 and state != "gap":
            impact = RISK_SHORT["CA"]
        rows.append([f"{index}. {label} {status}", fit(parts, 36), impact])
    return rows


def gap_box(d: DeckData) -> str:
    states = {key: control_state(d, DOMAIN_CODES[key]) for key, *_ in CONTROL_QUESTIONS}
    lines = ["3대 통제 공백" if any(state == "gap" for state, _ in states.values()) else "3대 통제 현황", ""]
    for number, (key, word, question) in zip("①②③", CONTROL_QUESTIONS, strict=True):
        codes = DOMAIN_CODES[key]
        state, code = states[key]
        if state == "gap":
            line = compact(d, code)
        elif state == "partial":
            line = f"L3 충족 · {compact(d, code)}"
        elif d.worst(codes) is None:
            line = "확인 중"
        else:
            line = f"L3 이상 {sum(d.score(c) is not None and d.score(c) >= 3 for c in codes)}/{len(codes)}"
        lines += [f"{number} {word} : {question}", line, ""]
    return "\n".join(lines[:-1])


def insights(d: DeckData) -> tuple[str, str, str]:
    """One sentence per executive: CIO (assets/cost), CAIO (demand/quality), CISO (identity/security)."""
    catalog = d.catalog
    waiting = d.score("OT-SY-24") is None
    spread = ""
    if catalog:
        who = ("통합 관측 대상이" if catalog.source == "통합 관측 생성월" else
               "Agent 365 목록 패키지가" if catalog.source.startswith("Agent 365") else "Azure 에이전트가")
        spread = f"{who} 월 {catalog.first}→{catalog.last}개로 늘고 "
    cost = "비용 구분은 확인 중" if waiting else compact(d, "OT-SY-24")
    action = ("전사 에이전트 목록과 비용 구분 체계 수립" if waiting or d.score("OT-SY-24") < 3
              else "전사 에이전트 목록과 비용 구분 체계 유지 점검")
    first = (f"{spread or '에이전트가 늘고 '}{cost} → {action}"
             if catalog or waiting else "자산·비용 관리 기준 충족 → 현 체계 유지")
    quality = d.worst_gap(("BI-SY-09", "BI-SY-11", "BI-SY-14", "DS-SY-02"))
    second = (f"{compact(d, quality)} → 배포 전 품질·규칙 점검을 승인 관문(Gate)으로 제도화"
              if quality else "수요 승인·품질 기준 충족 → 현 승인 관문 유지")
    security = [c for c in ("DS-SY-05", "BI-SY-14", "OE-SY-17", "OE-SY-19") if d.gaps((c,))]
    parts = [compact(d, c) for c in security[:2]]
    if d.conditional_access and d.conditional_access[0] < d.conditional_access[1]:
        parts.append(f"ID 접속 조건 제한 {d.conditional_access[0]}/{d.conditional_access[1]}")
    third = (f"{fit(parts, 26)} → 외부 접속·ID 접속 조건 제한 즉시 적용"
             if parts else "신원·보안 기준 충족 → 현 통제 유지")
    return first, second, third


def overview(d: DeckData) -> dict[int, str]:
    catalog = d.catalog
    registry = d.rate("registry.match")
    spread = (
        f"{catalog.last}개\n월 신규 목록 패키지 ({len(catalog.months)}개월 전 {catalog.first}개)"
        if catalog and catalog.source.startswith("Agent 365")
        else f"{catalog.last}개\n생성 시각 확인 통합 대상 ({len(catalog.months)}개월 전 {catalog.first}개)"
        if catalog and catalog.source == "통합 관측 생성월"
        else f"{catalog.last}개\n월 신규 Azure 에이전트 ({len(catalog.months)}개월 전 {catalog.first}개)" if catalog
        else f"{d.azure_agents() or 0}개\nAzure에서 확인된 에이전트"
    )
    if registry is not None:
        spread = f"{registry:.0%}\nRegistry - 공식 등록부 일치율"
    responsibility = d.percent("OE-SY-16")
    responsibility_label = "소유자 · 스폰서 지정 비율"
    if responsibility is None:
        responsibility = d.percent("BI-SY-13")
        responsibility_label = "플랫폼별 필수 자산 정보 확인 비율"
    first, second, third = insights(d)
    note = [f"1) 측정 {len(d.scored)}개 항목 기준"
            + (f" ({len(d.pending)}개 항목은 확인 중)" if d.pending else "")]
    package_note = ""
    if catalog is not None and catalog.source.startswith("Agent 365") and catalog.total:
        package_note = (f"※ 목록 패키지 {catalog.total}개는 플랫폼 미확인 앱(스토어 앱 포함)을 포함하며 직접 제작·구성은 "
                        f"{catalog.built}개({pct(catalog.built / catalog.total)}), 등록일은 이 테넌트 등록일과 다를 수 있음")
    return {
        23790: headline_overview(d),
        23810: f"{d.overall_label}\n종합 수준 ({'잠정, ' if d.provisional else ''}목표 L3.0)",
        23817: f"{d.passed} / {len(d.scored)}\nL3 충족 항목 수¹⁾",
        23825: spread,
        23834: f"{responsibility or '확인 중'}\n{responsibility_label}",
        23868: gap_box(d),
        23930: first,
        23967: second,
        24008: third,
        24030: "\n".join(part for part in (footer(d, 3, lead=note[0], limit=88), package_note) if part),
    }


# ---- slide 4 ---------------------------------------------------------------------------------
def method_texts(d: DeckData) -> dict[int, str]:
    tools = d.tools
    count = len(tools) if tools is not None else None
    intro = f"Microsoft 관리 도구 {count}종에서 " if count else "Microsoft 관리 도구에서 "
    stamp = d.collected_label()
    subscriptions, agents = d.subscriptions(), d.azure_agents()
    scope = (f"구독 {subscriptions}개" + (f" · 에이전트 {agents}개" if agents is not None else "")
             if subscriptions is not None else "승인된 Azure·Microsoft 365 범위")
    refs = d.value("run.evidence_sources")
    limit = ""
    if d.pending:
        limit = (f"확인 중 {len(d.pending)}개 ({pending_names(d)}) : {pending_reasons(d)} 후 판정, "
                 "점수 평균에서 제외하며 0점 아님")
    names = d.assessment.level_names or LEVEL_NAMES
    return {
        24053: f"{intro}읽기 전용으로 {len(d.items)}개 System Evidence를 추출해 5개 유형으로 분석하고, "
               "L1~L5 판정 기준으로 항목 · Lifecycle 단계별 수준을 평가하여 인터뷰 결과와 교차 검증",
        24128: f"I. {len(d.items)}개 항목 5개 분석 유형",
        24245: "\n".join([
            "진단 대상", scope, "수집 기간", stamp or "수집 일시 기록 없음",
            "수집 방식", "읽기 전용 · 관리자 읽기 증적",
            "증적 자료", f"수집 증적 참조 {refs}건" if refs else "API 응답 · 관리자 읽기 증적"]),
        24344: f"L1 {names[0]}\n" + d.band("L1", "충족 비율 0%"),
        24379: f"L2 {names[1]}\n" + d.band("L2", "충족 비율 0% 초과"),
        24415: f"L3 {names[2]} (목표)\n" + d.band("L3", "충족 비율 80% 이상"),
        24452: f"L4 {names[3]}\n" + d.band("L4", "충족 비율 90% 이상"),
        24490: f"L5 {names[4]}\n" + d.band("L5", "충족 비율 100%"),
        24529: ("수집 도구" + (f" ({count}종)" if count else "") + " : "
                + (" · ".join(tool_names(d, 4)) if tools else "Azure · Microsoft 365 관리 도구")),
        24569: f"보정 규칙 : System Evidence 점수가 인터뷰 점수보다 {CORRECTION_GAP:g}점 이상 낮으면 영역 점수를\n"
               "System Evidence 점수 + 1.0으로 하향 보정하고 '인터뷰-실측 괴리'로 별도 표기",
        24610: pick([f"※ {limit}", f"※ 확인 중 {len(d.pending)}개 - {pending_reasons(d)} 후 판정, 평균에서 제외"]
                    if d.pending else ["※ 모든 항목을 읽기 전용 수집 결과로 판정"], 88),
    }


def method_rows(d: DeckData) -> list[list[str]]:
    rows = [["분석 유형", "확인 내용", "항목 수"]]
    for key, _label, codes in d.groups():
        rows.append([f"{key} {GROUP_LONG[key]}", GROUP_FOCUS[key], str(len(codes))])
    return rows


# ---- slide 5 ---------------------------------------------------------------------------------
def headline_scores(d: DeckData) -> str:
    areas = d.assessment.areas
    ranked = sorted((a for a in areas.values() if a.final is not None), key=lambda a: (a.final, a.prefix))
    if not ranked:
        return "인터뷰 응답과 System Evidence가 모이면 Lifecycle 단계별 수준을 표시합니다"
    below = [a for a in ranked if a.final < TARGET_LEVEL]
    meet = len(ranked) - len(below)
    weakest = ranked[:2]
    names = " · ".join(d.area_name(a.prefix) for a in weakest)
    low = f"L{weakest[0].final:.1f}" + (f"~{weakest[1].final:.1f}" if len(weakest) > 1
                                       and weakest[1].final != weakest[0].final else "")
    first = (f"6개 Lifecycle 단계 중 {meet}개가 목표(L3)를 충족했으나 " if below and meet
             else "6개 Lifecycle 단계 모두 목표(L3)를 충족하나 " if not below
             else "6개 Lifecycle 단계 모두 목표(L3)에 미달하며 ")
    weak = f"{names} 단계가 {low}로 가장 약함"
    if d.corrected():
        tail = (", " + " · ".join(d.area_name(p) for p in d.corrected()[:2])
                + f" 단계는 인터뷰가 System Evidence보다 {CORRECTION_GAP:g}점 이상 높아 점수를 낮춰 보정")
    elif d.ahead():
        tail = ", 인터뷰 응답이 System Evidence보다 낮아 업무 절차·인식 정착 확인 필요"
    else:
        tail = ", 인터뷰와 System Evidence가 일치해 보정 없이 적용"
    return pick([first + weak + tail, first + weak], 112)


def partial_area(d: DeckData, prefix: str) -> bool:
    """True when a Lifecycle stage's System Evidence average leaves out items that are still being confirmed."""
    area = d.assessment.areas[prefix]
    return 0 < area.system_scored < area.system_total


def coverage_note(d: DeckData) -> str:
    counts = " · ".join(f"{d.area_name(prefix)} {d.assessment.areas[prefix].system_total}"
                        for prefix, *_ in AREAS)
    return f"※ 단계별 System Evidence 확인 항목 수 : {counts} (항목이 적은 단계는 점수 해석에 주의)"


def score_rows(d: DeckData) -> list[list[str]]:
    rows = [["Lifecycle 단계", "인터뷰 응답", "System Evidence", "최종 점수"]]
    for prefix, _sheet, _korean, _english, _description in AREAS:
        area = d.assessment.areas[prefix]
        system = f"{area.system:.1f}" + ("*" if partial_area(d, prefix) else "") \
            if area.system is not None else PENDING_LABEL
        final = "-" if area.final is None else f"{area.final:.1f}"
        if area.status == "인터뷰-실측 괴리":
            final += " ▼ 보정"
        elif area.status == "인터뷰 기준(실측 없음)":
            final += " (인터뷰 기준)"
        interview = f"{area.interview:.1f}" if area.interview is not None else "응답 대기"
        rows.append([d.area_label(prefix), interview, system, final])
    return rows


def score_box(d: DeckData) -> str:
    corrected = d.corrected()
    if corrected:
        names = " · ".join(d.area_name(p) for p in corrected[:3])
        return (f"{names}\n\n'통제한다'는 응답과 실제 설정이 다름\n\n→ 문서상 정책이 시스템에 적용되었는지 점검 필요")
    ahead = d.ahead()
    if ahead:
        names = " · ".join(d.area_name(p) for p, _gap in ahead[:2])
        return (f"{names}\n\nSystem Evidence가 최대 {ahead[0][1]:.1f}점 높음\n\n"
                "→ 인터뷰 응답이 낮은 이유 확인 필요")
    return ("인터뷰와 System Evidence 일치\n\n응답과 실제 설정 간 큰 차이 없음\n\n→ 현 수준의 근거를 신뢰할 수 있음")


# ---- slide 6 ---------------------------------------------------------------------------------
def matrix_rows(d: DeckData) -> list[list[str]]:
    items = list(d.items.values())
    count = len(items)
    split = (count + 1) // 2
    rows = [["코드 · 항목", "실측", "판정"] * 2]
    for index in range(split):
        row: list[str] = []
        for position in (index, index + split):
            if position >= count:
                row.extend(["", "", ""])
                continue
            code = items[position].code
            label = topic(d, code)
            if d.score(code) is None:
                row.extend([f"{code}\n{label}", "-", PENDING_LABEL])
                continue
            fraction, percent = d.fraction(code), d.percent(code)
            row.extend([
                f"{code}\n{label}",
                f"{fraction} ({percent})" if fraction and percent else fraction or d.metric_text(code),
                d.level(code),
            ])
        rows.append(row)
    return rows


def distribution(d: DeckData) -> list[int]:
    return [
        sum(item.score == 1 for item in d.scored), sum(item.score == 2 for item in d.scored),
        sum(item.score == 3 for item in d.scored), sum(item.score in (4, 5) for item in d.scored),
        len(d.pending),
    ]


def headline_matrix(d: DeckData) -> str:
    gaps = sorted(d.gaps(tuple(d.items)), key=lambda c: (d.score(c), c))
    top = [topic(d, code) for code in gaps[:3]]
    lead = f"측정 가능한 {len(d.scored)}개 항목 중 {d.passed}개가 L3 목표를 충족했으나"
    tail = f" {' · '.join(top)} 등 {len(gaps)}개 항목은 L3 미달" if gaps else " L3 미달 항목은 없음"
    wait = f"이며 {len(d.pending)}개 항목은 확인 중" if d.pending else ""
    return pick([lead + tail + wait, lead + tail], 112)


def matrix_box(d: DeckData) -> str:
    gaps = sorted(d.gaps(tuple(d.items)), key=lambda c: (d.score(c), c))
    if not gaps:
        return "L3 미달 없음\n\n측정된 모든 항목이 L3 이상\n\n→ 정기 재점검으로 유지 확인"
    names = " · ".join(topic(d, code) for code in gaps[:3])
    return f"L3 미달 {len(gaps)}개 항목\n\n{names} 등\n\n→ 설정 변경 중심이라 빠른 개선 가능"


def matrix_footer(d: DeckData) -> str:
    base = "판정 기준 : 항목별 충족 비율 L1~L5 (L3 = 80% 이상 충족, 목표)"
    if d.pending:
        return f"※ {base}, 확인 중 {len(d.pending)}개는 {pending_reasons(d)} 후 판정"
    return f"※ {base}"


# ---- slide 7 ---------------------------------------------------------------------------------
def headline_creation(d: DeckData) -> str:
    catalog = d.catalog
    creation = d.gaps(DOMAIN_CODES["creation"])
    worst = d.worst_gap(DOMAIN_CODES["creation"])
    if catalog and catalog.source == "통합 관측 생성월":
        return f"MS·이기종 관측 대상 중 생성 시각 확인 {catalog.total}개 - 플랫폼별 구성 상태와 생성월 분포를 함께 확인"
    if catalog is None:
        return ("신규 에이전트 확산 추이는 등록 목록 수집 후 표시하며, 현재 "
                + (d.long_fact(worst) if worst else "생성 통제는 기준을 충족"))
    growth = f"({catalog.growth:.1f}배)" if catalog.growth and catalog.growth > 1 else ""
    package = catalog.source.startswith("Agent 365")
    source = "Agent 365 목록 패키지(스토어 앱 포함)가" if package else "AI 에이전트 신규 생성이"
    built = (f"직접 제작·구성은 {catalog.built}개({pct(catalog.built / catalog.total)})뿐이고" if package
             else f"직접 만든 에이전트는 {catalog.built}개({pct(catalog.built / catalog.total)})뿐이고")
    word = "늘었으나" if catalog.last > catalog.first else "이어졌으나"
    lead = f"{source} 월 {catalog.first}개 → {catalog.last}개{growth}로 {word}"
    if not creation:
        return pick([f"{lead} 만드는 쪽 통제는 기준을 충족"], 112)
    return pick([
        f"{lead} {built}, {d.long_fact(worst)}",
        f"{lead} {built}, {d.fact(worst)}",
        f"{lead} {d.fact(worst)} - {risk_short(d, worst)}",
    ], 118)


def creation_caption(d: DeckData) -> str:
    catalog = d.catalog
    if catalog is None:
        return "신규 등록 이력은 등록 목록 수집 후 표시"
    if catalog.source == "통합 관측 생성월":
        return f"생성 시각 확인 {catalog.total}개 중 생성·등록·배포 확인 {catalog.built}개 - 실행 이력 아님"
    owners = d.catalog_owner_clause()
    if catalog.source.startswith("Agent 365"):
        parts = [f"{len(catalog.months)}개월 누적 목록 패키지 {catalog.total}개 중 직접 제작·구성 {catalog.built}개"
                 f"({pct(catalog.built / catalog.total)})", owners]
    else:
        parts = [f"{len(catalog.months)}개월 누적 신규 에이전트 {catalog.total}개"]
    return fit([p for p in parts if p], 56, sep=" · ")


def creation_insight(d: DeckData) -> str:
    worst = d.worst_gap(DOMAIN_CODES["creation"])
    catalog = d.catalog
    spread = "목록 패키지가 빠르게 늘었는데 " if catalog and catalog.growth and catalog.growth > 1 else ""
    if worst:
        return f"시사점\n{spread}{compact(d, worst)} → 허용 범위 결정 필요"
    return "시사점\n만드는 쪽 통제가 기준을 충족 - 확산 시 유지 점검"


def creation_notes(d: DeckData) -> list[str]:
    """Footnote lines on how to read the monthly package chart."""
    catalog = d.catalog
    if catalog is not None and catalog.source == "통합 관측 생성월":
        return ["※ MS·이기종 통합 관측 대상의 생성월 분포. 생성 시각 미확인은 제외",
                "※ Foundry 생성·등록, Copilot 게시, 이기종 원본 ID 연결 기준. 실행 성공·과거 승인 이력 아님"]
    if catalog is None or not catalog.source.startswith("Agent 365"):
        return []
    lines = ["※ Agent 365 목록 패키지 기준 · 플랫폼 미확인 앱(스토어 앱 포함) · 등록일은 이 테넌트 등록일과 다를 수 있음"]
    agents = d.azure_agents()
    if agents:
        lines.append(f"※ 직접 제작·구성 {catalog.built}개(Agent 365 목록)와 Azure 에이전트 {agents}개(Azure 수집)는 "
                     "서로 다른 모집단")
    return lines


TABLE_LABEL = {
    "DM-SY-01": "DM-SY-01 역할 할당 확인 환경", "DS-SY-02": "DS-SY-02 유출 방지 규칙(DLP)",
    "BI-SY-08": "BI-SY-08 관리자 보호(관리형 환경)",
}


def creation_rows(d: DeckData) -> list[list[str]]:
    rows = [["항목", "실측 결과", "L3 목표 기준", "판정"]]
    for code in ("DM-SY-01", "DS-SY-02", "BI-SY-08"):
        if code not in d.items:
            continue
        target = f"기준 충족 {d.l3_min(code):.0%} 이상"
        label = TABLE_LABEL[code]
        if d.score(code) is None:
            rows.append([label, d.pending_note(code), target, PENDING_LABEL])
            continue
        rows.append([label, d.fact(code), target, d.level(code)])
    return rows


# ---- slide 8 ---------------------------------------------------------------------------------
def ca_phrase(d: DeckData) -> str | None:
    if not d.conditional_access:
        return None
    applied, total = d.conditional_access
    if applied == 0:
        return f"에이전트 ID {total}개 모두 접속 조건(위치·기기 등)을 제한하는 규칙이 없어"
    if applied < total:
        return f"에이전트 ID {total}개 중 {applied}개에만 접속 조건 제한 규칙이 있어"
    return None


HEAD_CONSEQUENCE = {"DP-SY-15": "소유자·권한 기본값의 일괄 관리와", "DS-SY-03": "소유자·권한 기본값의 일괄 관리와"}


def headline_identity(d: DeckData) -> str:
    imperfect = [c for c in IDENTITY_BARS if d.counts(c) and d.counts(c)[0] < d.counts(c)[1]]
    first = sorted(imperfect, key=lambda c: (d.score(c), IDENTITY_BARS.index(c)))[:1]
    parts = [d.long_fact(c) for c in first]
    lead = HEAD_CONSEQUENCE.get(first[0], "사고 시 책임 추적과") if first else "사고 시 책임 추적과"
    ca = ca_phrase(d)
    if parts and ca:
        return pick([f"{parts[0]}, {ca} {lead} 무단 접근 차단에 공백이 있을 수 있음",
                     f"{parts[0]}, {ca} 접근 통제에 공백"], 118)
    if parts:
        return f"{parts[0]} - {d.risk(first[0])}"
    if ca:
        return f"{ca} 무단 접근 차단에 공백이 있을 수 있음"
    good = [c for c in IDENTITY_BARS if d.score(c) is not None]
    if good:
        return "청사진 연결 · 담당자 지정 · 권한 관리가 목표를 충족하며 신규 에이전트에도 같은 기준 적용 필요"
    return "에이전트 ID 청사진 연결 · 권한 지표는 확인 후 표시"


def identity_weak(d: DeckData) -> str | None:
    candidates = [(d.score(code), d.ratio(code) or 0, code) for code in IDENTITY_BARS
                  if d.score(code) is not None and d.score(code) < 5]
    if d.conditional_access and d.conditional_access[0] < d.conditional_access[1]:
        candidates.append((2 if d.conditional_access[0] else 1, 0.0, "CA"))
    return min(candidates)[2] if candidates else None


def identity_insight(d: DeckData) -> str:
    weak = identity_weak(d)
    if weak is None:
        return ("청사진 연결 · 권한 지표가 목표 이상이다\n\n청사진 연결 · 담당자 지정 · 권한 범위가 목표 이상\n\n"
                "→ 신규 에이전트에도 같은 기준을 적용하고 분기마다 재점검")
    if weak == "CA" and d.conditional_access:
        applied, total = d.conditional_access
        detail = (f"접속 조건 제한 규칙이 있는 에이전트 ID는 {total}개 중 {applied}개 - "
                  "ID가 탈취되면 제한 없이 쓰일 가능성")
    else:
        detail = d.gap_line(weak)
    return f"{IDENTITY_TITLE[weak]}\n\n{detail}\n\n→ {IDENTITY_ACTION[weak]}"


def identity_recommendations(d: DeckData) -> str:
    ranked = [(d.score(code), d.ratio(code) or 0, code) for code in IDENTITY_BARS
              if d.score(code) is not None and d.score(code) < 5]
    imperfect = [(3, d.ratio(code) or 0, code) for code in IDENTITY_BARS
                 if d.counts(code) and d.counts(code)[0] < d.counts(code)[1]
                 and d.score(code) is not None and d.score(code) >= 5]
    if d.conditional_access and d.conditional_access[0] < d.conditional_access[1]:
        ranked.append((1 if not d.conditional_access[0] else 2, 0.0, "CA"))
    actions = [RECOMMEND[code] for _s, _r, code in sorted(ranked + imperfect)][:3]
    for filler in ("신규 에이전트 ID 연결 의무화", "담당자 분기 재검증", "권한 변경 모니터링"):
        if len(actions) < 3 and filler not in actions:
            actions.append(filler)
    title = "권고 (즉시)" if ranked else "권고 (유지)"
    return title + "\n" + "\n".join(f"{n} {a}" for n, a in zip("①②③", actions, strict=True))


def identity_rows(d: DeckData) -> list[list[str]]:
    def gap(code: str, label: str) -> tuple[str, str]:
        pair = d.counts(code)
        if pair is None:
            return label, PENDING_LABEL
        return label, f"{pair[1] - pair[0]:g} / {pair[1]:g}"

    left = [gap("OE-SY-16", "소유자 · 스폰서 미지정"), gap("DP-SY-15", "청사진 미연결 에이전트"),
            gap("DS-SY-03", "청사진 미연결 ID")]
    right = [gap("OE-SY-17", "쓰기 · 전체 제어 권한"), gap("OE-SY-19", "플랫폼별 인증 · 권한 구성")]
    if d.conditional_access:
        applied, total = d.conditional_access
        right.append(("접속 조건 제한 없음", f"{total - applied} / {total}"))
    else:
        right.append(("", ""))
    return [["고아 · 미지정 구분", "해당 수 / 전체", "과다 권한 유형", "해당 수 / 전체"],
            *[[a, b, c, e] for (a, b), (c, e) in zip(left, right, strict=True)]]


# ---- slide 9 ---------------------------------------------------------------------------------
def card_ratio(d: DeckData, code: str) -> float | None:
    if code == "BI-SY-29":
        return d.rate("evaluation.predeploy")
    if code == "OT-SY-33":
        return d.rate("security.exposure")
    return d.ratio(code) if d.score(code) is not None else None


def security_cards(d: DeckData) -> list[str]:
    measured = [c for c in SECURITY_POOL if d.score(c) is not None]
    ranked = sorted(measured, key=lambda c: (d.ratio(c) if d.ratio(c) is not None else 1, SECURITY_POOL.index(c)))
    chosen = ranked[:2]
    for code in SECURITY_POOL:
        if len(chosen) < 2 and d.score(code) is None:
            chosen.append(code)
    if d.rate("security.exposure") is not None:
        chosen = [*chosen[:1], "OT-SY-33"]
    return ["BI-SY-29" if d.rate("evaluation.predeploy") is not None else "BI-SY-09", *chosen[:2]]


def card_texts(d: DeckData, code: str) -> dict[str, str]:
    if code == "BI-SY-29":
        floor = d.rate("report.target.evaluation.predeploy") or 0.8
        return {
            "title": "배포 전 평가 이력", "value": f"{d.rate('evaluation.predeploy'):.0%}",
            "detail": f"배포 {d.value('evaluation.deployed') or 0:g}개 중 평가 {d.value('evaluation.evaluated') or 0:g}개",
            "good": f"완료 {d.value('evaluation.evaluated') or 0:g}",
            "bad": f"미완료 {d.value('evaluation.missing') or 0:g}", "target": f"L3 목표 : {floor:.0%} 이상",
        }
    if code == "OT-SY-33":
        floor = d.rate("report.target.security.exposure") or 0.9
        return {
            "title": "민감 데이터 노출", "value": f"{d.rate('security.exposure'):.0%}",
            "detail": f"고위험 {d.value('security.exposure.total') or 0:g}건 중 미조치 "
                      f"{d.value('security.exposure.open') or 0:g}건",
            "good": f"조치 {d.value('security.exposure.remediated') or 0:g}",
            "bad": f"미조치 {d.value('security.exposure.open') or 0:g}", "target": f"L3 목표 : {floor:.0%} 이상",
        }
    pattern, good, bad = CARD[code]
    title = f"{CARD_TITLE[code]} ({code})"
    if d.score(code) is None:
        return {"title": title, "value": PENDING_LABEL, "detail": d.pending_note(code), "good": "", "bad": "",
                "target": f"L3 목표 : {d.l3_min(code):.0%} 이상"}
    pair = d.counts(code)
    ratio = d.ratio(code)
    detail = pattern.format(n=f"{pair[0]:g}", d=f"{pair[1]:g}") if pair else d.level(code)
    if code == "BI-SY-09" and d.collection and d.collection.evaluations and pair:
        runs = d.collection.evaluations
        passed = sum(r.passed_items or 0 for r in runs)
        total = sum(r.total_items or 0 for r in runs)
        if total:
            detail = f"평가 실행 {pair[0]:g}/{pair[1]:g}개 · 항목 통과 {passed}/{total}"
    return {
        "title": title, "value": pct(ratio) if ratio is not None else d.level(code), "detail": detail,
        "good": f"{good} {pair[0]:g}" if pair else "", "bad": f"{bad} {pair[1] - pair[0]:g}" if pair else "",
        "target": f"L3 목표 : {d.l3_min(code):.0%} 이상",
    }


def headline_security(d: DeckData) -> str:
    strong = [c for c in ("BI-SY-09", "BI-SY-11") if d.score(c) is not None and d.score(c) >= 4]
    weak = sorted((c for c in SECURITY_POOL if d.score(c) is not None and d.score(c) < 3),
                  key=lambda c: (d.score(c), c))
    wait = [c for c in SECURITY_POOL if d.score(c) is None]
    strong_text = " · ".join(topic(d, c) for c in strong)
    weak_text = fit([d.fact(c) for c in weak[:2]], 46)
    risks = " · ".join(dict.fromkeys(risk_short(d, c) for c in weak[:2]))
    wait_text = f" (확인 중 : {' · '.join(topic(d, c) for c in wait[:2])})" if wait else ""
    if weak and strong:
        return pick([f"{strong_text} 등은 갖췄으나 {weak_text} - {risks}{wait_text}",
                     f"{strong_text} 등은 갖췄으나 {weak_text}{wait_text}"], 112)
    if weak:
        return pick([f"{weak_text} - {risks}{wait_text}", f"{weak_text}{wait_text}"], 112)
    return f"품질 · 보안 점검 설정이 기준을 충족{wait_text}"


def security_box(d: DeckData) -> tuple[str, str]:
    protect = [compact(d, c) for c in ("DS-SY-06", "DS-SY-07") if c in d.items and d.score(c) is not None]
    first = "\n".join(protect[:2]) if protect else "도구 연결 보호는 확인 중"
    weak = [c for c in SECURITY_POOL if d.score(c) is not None and d.score(c) < 3]
    if weak:
        names = " · ".join(topic(d, c) for c in sorted(weak, key=lambda c: (d.score(c), c))[:2])
        second = f"{names} 공백 → 접근 시도·규칙 위반 방치 가능성, 적용 결정 필요"
    else:
        second = "품질 · 보안 설정이 기준을 충족 - 재점검으로 유지 확인"
    return first, second


def security_notes(d: DeckData) -> str:
    """Why a security card or row is still being confirmed, in the slide's footnote."""
    parts = []
    for code in SECURITY_POOL:
        if code not in d.items or d.score(code) is not None:
            continue
        note = d.pending_note(code)
        if code == "BI-SY-10" and "구독" in note:
            note += "(Defender 평가 반영 후 판정)"
        parts.append(note if code == "BI-SY-10" else f"{topic(d, code)} {note}")
    return ", ".join(parts)


def defender_rows(d: DeckData) -> list[list[str]] | None:
    if d.collection is None or not d.collection.defender_plans:
        return None
    names = {"CloudPosture": "보안 상태 점검(CSPM)", "AI": "AI 위협 방지",
             "Containers": "컨테이너 보호", "KeyVaults": "비밀 키 보관소 보호", "Api": "API 보호"}
    plans: dict[str, list[bool]] = {}
    for plan in d.collection.defender_plans:
        plans.setdefault(plan.plan, []).append((plan.tier or "").lower() == "standard")
    rows = [["Defender 보안 점검 기능", "유료 보호 적용", "점검 구독", "상태"]]
    for plan, flags in plans.items():
        enabled = sum(flags)
        state = "전체 적용" if enabled == len(flags) else "일부 적용" if enabled else "기본(무료) 단계"
        rows.append([names.get(plan, plan), f"{enabled}개", f"{len(flags)}개", state])
    for code in ("BI-SY-10", "OT-SY-25"):
        if code in d.items and d.score(code) is None:
            rows.append([d.label(code), "-", "-", d.pending_note(code)])
    return rows[:6]


def fallback_security_rows(d: DeckData) -> list[list[str]]:
    rows = [["점검 항목", "충족 / 대상", "충족 비율", "판정"]]
    for code in SECURITY_POOL:
        if code not in d.items:
            continue
        pair = d.counts(code)
        rows.append([d.label(code), f"{pair[0]:g} / {pair[1]:g}" if pair else d.pending_note(code),
                     d.percent(code) or "-", d.level(code)])
    return rows


def exposure_rows(d: DeckData) -> list[list[str]] | None:
    if d.rate("security.exposure") is None:
        return None
    rows = [["민감정보 유형", "노출", "미조치", "주요 노출 경로"]]
    for category, label in (("national_id", "고유 식별 정보"), ("personal", "개인 정보"), ("legal", "법률"),
                            ("financial", "재무"), ("other", "기타")):
        total = d.value(f"security.exposure.{category}.total")
        remaining = d.value(f"security.exposure.{category}.open")
        rows.append([label, "-" if total is None else f"{total:g}", "-" if remaining is None else f"{remaining:g}",
                     "-"])
    return rows


# ---- slide 10 --------------------------------------------------------------------------------
def headline_ops(d: DeckData) -> str:
    codes = DOMAIN_CODES["visibility"]
    gaps = sorted(d.gaps(codes), key=lambda c: (d.score(c), c))
    good = [c for c in ("OE-SY-20", "OE-SY-21", "OT-SY-26") if d.score(c) is not None and d.score(c) >= 4]
    gap_text = fit([d.fact(c) for c in gaps[:2]], 44)
    good_text = " · ".join(topic(d, c) for c in good[:3])
    cost = ("에이전트별 비용은 청구 반영 후에야 확인 가능" if d.score("OT-SY-24") is None
            else d.fact("OT-SY-24"))
    if gaps and good:
        return pick([f"{good_text} 설정은 갖췄으나 {gap_text} - 사고 원인 추적이 불완전할 수 있음, {cost}",
                     f"{good_text} 설정은 갖췄으나 {gap_text}, {cost}"], 112)
    if gaps:
        return f"{gap_text} - 사고 원인 추적이 불완전할 수 있음, {cost}"
    return f"실행 기록 · 알림 · 예산 설정이 기준을 충족하며 {cost}"


def ops_bar(d: DeckData, code: str) -> tuple[str, str, str, float | None]:
    ratio = d.ratio(code) if d.score(code) is not None else None
    if ratio is None:
        return OPS_NAMES[code], PENDING_LABEL, "청구 반영 후" if code == "OT-SY-24" else "확인 후", None
    return OPS_NAMES[code], pct(ratio), d.fraction(code) or d.level(code), ratio


def ops_rows(d: DeckData) -> list[list[str]]:
    rows = [["항목", "실측 결과", "L3 목표 기준", "판정"]]
    retention = None
    if d.collection and d.collection.logs:
        days = [log.retention_days for log in d.collection.logs if log.enabled and log.retention_days]
        retention = min(days) if days else None
    for code in ("OE-SY-18", "OE-SY-22", "OT-SY-24", "OT-SY-26"):
        if code not in d.items:
            continue
        target = f"기준 충족 {d.l3_min(code):.0%} 이상"
        label = f"{code} {OPS_ROW_NAMES[code]}"
        if d.score(code) is None:
            rows.append([label, d.pending_note(code), target, PENDING_LABEL])
            continue
        result = d.fact(code)
        if d.currency(code) and d.percent(code):
            result += f"({d.percent(code)})"
        if code == "OE-SY-22" and retention:
            result = f"{d.fact(code)} (Azure workspace 최소 {retention}일)"
        rows.append([label, result, target, d.level(code)])
    return rows


def ops_box(d: DeckData) -> str:
    gaps = d.gaps(("OE-SY-18", "OE-SY-22"))
    waiting = d.score("OT-SY-24") is None
    fraction = d.fraction("OT-SY-26")
    first = (f"예산 초과 알림은 설정됨 ({fraction}),\n" if d.score("OT-SY-26") is not None and fraction
             else "예산 · 알림 설정은 점검 중,\n")
    second = "그러나 기록 · 비용 구분은 보완 필요\n" if gaps or waiting else "기록 · 비용 통제 유지\n"
    third = []
    if gaps:
        third.append(compact(d, gaps[0]))
    if waiting:
        third.append("에이전트별 비용은 확인 중")
    return first + second + (", ".join(third) or "정기 재점검으로 유지 확인")


def cost_note(d: DeckData) -> str:
    """Footnote for a billed amount that is still too small for the ratio to mean much."""
    return "청구 금액이 아직 적어 비율은 참고용" if d.small_amount("OT-SY-24") else ""


HOSTING_RESOURCE = ("/microsoft.web/serverfarms/", "/microsoft.web/sites/", "/microsoft.app/")


def cost_notes(d: DeckData) -> list[str]:
    """Footnote lines that tell how much billing the monthly cost chart really covers."""
    lines: list[str] = []
    collection = d.collection
    rows = [row for row in (collection.costs if collection else []) if row.usage_date]
    days = sorted({re.sub(r"\D", "", str(row.usage_date))[:8] for row in rows
                   if len(re.sub(r"\D", "", str(row.usage_date))) >= 8})
    if days:
        def day(value: str) -> str:
            return f"{int(value[4:6])}/{int(value[6:8])}"
        latest = [value for value in days if value[:6] == days[-1][:6]]
        span = day(latest[0]) if len(latest) == 1 else f"{day(latest[0])}~{day(latest[-1])}"
        suffix = "하루치" if len(latest) == 1 else f"{len(latest)}일치"
        lines.append(f"※ {int(days[-1][4:6])}월 금액은 수집된 청구 {span} {suffix}이며 월 전체 비용이 아님")
    history = d.value("cost.history")
    if isinstance(history, str):
        empty = [month for month in history.split(",")[-6:] if d.value(f"cost.month.{month}.total") is None]
        if empty and len(empty) < len(history.split(",")[-6:]):
            span = f"{int(empty[0][4:])}월" if len(empty) == 1 else f"{int(empty[0][4:])}~{int(empty[-1][4:])}월"
            lines.append(f"※ {span}은 조회 기간 안에 청구 내역이 없음")
    if d.currency("OT-SY-24") and rows:
        total = sum(row.amount for row in rows)
        hosting = sum(row.amount for row in rows if any(key in row.resource_id.lower() for key in HOSTING_RESOURCE))
        text = "※ 직접 귀속은 비용 리소스가 한 에이전트에만 연결된 비율이며 에이전트별 사용 비용이 아닌 리소스 단위 귀속"
        if total and hosting / total >= 0.5:
            text += f"(금액의 {pct(hosting / total)}가 호스팅 요금)"
        lines.append(text)
    return lines


def usage_lines(d: DeckData) -> list[str] | None:
    usage = d.usage
    if usage is None:
        return None
    observed = usage.active + usage.idle
    return [
        f"30일 내 사용 : {usage.active}개" + (f" ({pct(usage.active / observed)})" if observed else ""),
        f"30일 미사용 : {usage.idle}개" + (f" ({pct(usage.idle / observed)})" if observed else ""),
        f"사용 현황 확인 중 : {usage.unobserved}개"
        + (f" (플랫폼 미확인 앱 {usage.provided}개 제외)" if usage.provided else ""),
    ]


def usage_note(d: DeckData) -> str:
    usage = d.usage
    if usage is None or not usage.active + usage.idle:
        return ""
    return f"사용 비율은 사용 현황이 확인된 {usage.active + usage.idle}개 기준"


# ---- slide 11 --------------------------------------------------------------------------------
PHASE_LABEL = {1: "Phase 1", 2: "Phase 2", 3: "Phase 3"}


def headline_plan(d: DeckData) -> str:
    gaps = len(d.gaps(tuple(d.items)))
    path = d.target_path()
    tasks = d.tasks()
    first = [t for t in tasks if t["phase"] == 1]
    if not gaps and not d.pending:
        return "모든 항목이 L3 이상이므로 개선 과제는 현 수준 유지와 정기 재점검에 집중"
    lead = f"L3 미달 {gaps}개 항목" + (f"과 확인 중 {len(d.pending)}개 항목" if d.pending else "")
    goal = f"6개월 목표(안) 관리 수준 L{path[-1]:.1f}" if path else "관리 수준 목표(안) 수립"
    raising = " · L3 항목은 L4 상향 검토" if any(t["raise"] for t in tasks) else ""
    owners: dict[str, list[str]] = {}
    for task in first[:4]:
        owners.setdefault(str(task["owner"]), []).append(str(task["short"]))
    asks = " · ".join(f"{owner}({names[0]})" for owner, names in list(owners.items())[:2])
    options = [f"{lead}을 Phase 1~3으로 개선{raising}, {goal} - 우선 30일 내 {asks} 착수 결정 필요",
               f"{lead}을 Phase 1~3으로 개선{raising}, {goal}",
               f"{lead}을 Phase 1~3으로 개선, {goal}",
               f"{lead} 개선 일정과 주관 확정 필요"]
    return pick(options if asks else options[1:], 118)


def phase_boxes(d: DeckData) -> list[str]:
    tasks = d.tasks()
    heads = ("Phase 1 · 즉시 조치 (~30일)", "Phase 2 · 통제 체계 (~90일)", "Phase 3 · 자동화 (~6개월)")
    fallback = ("신규 에이전트 통제 기준 유지", "정책 · 설정 정기 점검", "목표 유지 · 정기 재점검")
    boxes = []
    for phase, head, other in zip((1, 2, 3), heads, fallback, strict=True):
        names = [str(t["short"]) for t in tasks if t["phase"] == phase]
        boxes.append(f"{head}\n" + (fit(names, 24, sep=" · ") if names else other))
    return boxes


def plan_rows(d: DeckData) -> list[list[str]]:
    rows = [["단계", "개선 과제", "대상 항목", "주관", "목표 지표"]]
    for task in d.tasks()[:8]:
        codes = list(task["codes"])
        rows.append([
            PHASE_LABEL[int(task["phase"])], str(task["name"]), " · ".join(codes[:2]), str(task["owner"]),
            str(task["target"]),
        ])
    if len(rows) == 1:
        rows.append(["Phase 3", "현 수준 유지 · 정기 재점검", "전체 항목", "CIO", "L3 이상 유지"])
    return rows


# ---- slide 12 --------------------------------------------------------------------------------
ITERATION = (1, 1, 2, 2, 3)


def target_rows(d: DeckData) -> list[list[str]]:
    rows = [["대상 영역", "주요 근거 (실측)", "수준", "추진 단계"]]
    for index, domain in enumerate(d.domains()):
        evidence = fit(d.evidence(tuple(domain["codes"]), 2), 36, sep=" · ")
        level = f"L{domain['level']:.1f}" if domain["level"] is not None else PENDING_LABEL
        rows.append([str(domain["title"]), evidence, level, f"Iteration {ITERATION[min(index, 4)]}"])
    return rows


def next_texts(d: DeckData) -> dict[int, str]:
    domains = d.domains()
    scored = [dom for dom in domains if dom["level"] is not None]
    first = domains[:2]
    names = ", ".join(str(dom["short"]).replace(" · ", "·") for dom in first)
    operating = all(dom["key"] in ("identity", "creation", "security") for dom in first)
    if scored:
        low, high = scored[0]["level"], scored[min(1, len(scored) - 1)]["level"]
        span = f"L{low:.1f}" + (f"~{high:.1f}" if high != low else "")
        criteria = f"① 실측 수준 최하위 ({span})"
    else:
        criteria = "① 실측 수준 최하위"
    terms = ", ".join(DOMAIN_TERMS[str(dom["key"])] for dom in first)
    short = [str(dom["short"]).replace(" · ", "·") for dom in domains]
    group = [", ".join(short[0:2]), ", ".join(short[2:4]), ", ".join(short[4:]) or "전 영역 정착 · 자동화"]
    return {
        40776: "결정이 필요한 사항 : 가장 취약한 영역을 1차 대상으로 정하고 Iteration 범위 · 기간을 확정 - "
               "Framework 설계 → Platform 구축 → 점검을 반복해 정보 유출 · 책임 추적 · 비용 통제 위험을 단계적으로 줄임",
        43822: f"{criteria}\n② 사고 시 영향 · 위험 노출 규모\n③ 기존 라이선스로 단기 효과\n\n"
               f"→ 1차 대상 :{' 운영통제' if operating else ''}\n({names})",
        43904: f"· 운영통제 프로세스 · 통제 기준 정의\n  ({terms})\n· 역할 · 책임(R&R) 및 정책 · 표준 수립\n"
               "· 통제 KPI 및 L3 판정 기준 정의",
        43951: "· Agent 365 · Entra · Purview · Defender 통제 적용\n  (Agent ID, 조건부 접근, DSPM for AI)\n"
               "· Agent Registry - 공식 등록부 자동 대사\n· 운영통제 Dashboard (Inventory & Status)",
        44057: f"Iteration 1 · 운영통제 (1~3개월)\n{group[0]}",
        44086: f"Iteration 2 · 확대 (4~6개월)\n{group[1]}",
        44116: f"Iteration 3 · 고도화 (7~9개월)\n{group[2]}",
        44179: "※ Iteration 범위 · 기간은 계획(안)이며 고객 우선순위 협의 후 확정, 수준은 System Evidence 기준",
    }


# ---- notes -----------------------------------------------------------------------------------
def note_refs(d: DeckData, page: int) -> list[str]:
    """Evidence references behind the page, kept in the speaker notes for traceability."""
    codes = NOTE_CODES.get(page, ())
    prefixes = NOTE_PREFIXES.get(page, ())
    refs: set[str] = set()
    for key, metric in d.metrics.items():
        if key.startswith(prefixes) or any(key == f"se.{c}" or key.startswith(f"se.{c}.") for c in codes):
            refs.update(metric.evidence_refs)
    return sorted(refs)


def note_limits(d: DeckData, page: int) -> list[str]:
    lines = ["해석 범위"]
    lines.append("- 판단·권고·기간·주관은 검토안이며 업무 영향의 발생·금액·정책 실효성을 추정하지 않습니다.")
    lines.append("- 확인 중 항목은 0점이나 L1이 아니며 점수 평균에서 제외됩니다.")
    if page in (1, 2, 3, 4, 5):
        finals = [(p, a.final) for p, a in d.assessment.areas.items() if a.final is not None]
        lines += [
            "- 종합 수준은 영역별 최종 점수의 동일 가중 평균이며 항목 전체의 단순 평균이 아닙니다. 영역별 최종: "
            + ", ".join(f"{p}={v:.1f}" for p, v in finals),
            f"- 인터뷰 보정: 인터뷰가 System Evidence보다 {CORRECTION_GAP:g}점 이상 높은 영역만 최종 = System Evidence + 1.0을 적용하고, "
            "그 외에는 인터뷰 점수를 최종으로 사용합니다. 26개 System Evidence 항목의 L1~L5 판정은 변경하지 않습니다.",
            "- 영역별 입력: " + "; ".join(
                f"{p}: 인터뷰 {a.interview if a.interview is not None else '-'}, "
                f"System Evidence {a.system if a.system is not None else '-'}, "
                f"최종 {a.final if a.final is not None else '-'}"
                f" ({a.status})" for p, a in d.assessment.areas.items()),
        ]
    if page in (6, 10):
        lines.append("- Agent 365 목록 패키지에는 플랫폼 미확인 앱(스토어 앱 포함)이 포함되어 고유 에이전트 수가 아니며, "
                     "등록일은 이 테넌트 등록일과 다를 수 있습니다. 직접 제작·구성 여부는 플랫폼 값으로 구분했고 "
                     "월 경계는 KST 기준입니다. 사용자·세션 지표는 패키지별이며 합산하지 않습니다.")
    if page == 7:
        lines.append("- 접속 조건 제한(조건부 접근)은 명시적으로 활성화된 에이전트 ID 대상 구성만 확인했으며 "
                     "26개 항목 판정에 합산하지 않습니다.")
    if page == 8:
        lines.append("- Defender 플랜은 조회된 구독별 요금 단계이며 보안 권고는 구독별로 생성·반영된 범위만 판정합니다.")
    if page == 9:
        lines.append("- 충족 비율은 설정·기록 기준이며 기록 보관 기간은 확인한 최소값입니다. 비용은 수집된 청구 일수 기준이며 "
                     "직접 귀속은 리소스 단위 귀속입니다.")
    return lines

