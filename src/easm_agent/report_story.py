"""Executive narrative data for the report deck: plain-language facts computed from collected data.

Everything here is pure text/number logic. Slide geometry stays in report_pptx so the story can be
verified without rendering. A value that was not collected never becomes 0 or L1: the sentence falls
back to a plain "being confirmed" wording or to another collected indicator.
"""

from __future__ import annotations

import calendar
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from functools import cached_property

from easm_agent.deck_model import (
    AREAS,
    KINDS,
    TARGET_LEVEL,
    Assessment,
    round1,
)
from easm_agent.models import Collection
from easm_agent.report_backdata import ReportMetric
from easm_agent.report_terms import (
    AMOUNT_FACTS,
    AREA_KO,
    DEFAULT_GROUPS,
    DOMAIN_OWNER,
    DOMAINS,
    FACTS,
    GLOSSARY,
    LABELS,
    PENDING_BY_CODE,
    PENDING_BY_REASON,
    PENDING_REASON_PLAIN,
    PERSPECTIVES,
    TASKS,
    ZERO_LONG,
)

DEFAULT_CUSTOMER = "<고객사>"
KST = timezone(timedelta(hours=9))
L3_FALLBACK = 0.8
L4_FLOOR = 0.9
GAP_LEVEL = 3
AHEAD_MARGIN = 1.0
BUILT_NOT_AVAILABLE = "Not Available"
PENDING_LABEL = "확인 중"
SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹"


def em(text: str) -> float:
    """Approximate width in em: wide glyphs count 1, Latin text about half."""
    total = 0.0
    for char in text:
        if char == " ":
            total += 0.3
        elif char == "·":
            total += 0.4
        elif unicodedata.east_asian_width(char) in "WF" or ord(char) > 0x2000:
            total += 1.0
        else:
            total += 0.55
    return total


def capacity(width_in: float, size_pt: float, lines: int = 1) -> float:
    return (width_in - 0.25) * 72 / size_pt * lines * (0.95 if lines > 1 else 1.0)


def fit(parts: list[str], limit: float, sep: str = ", ") -> str:
    """Longest prefix of the parts that stays inside the limit (never empty)."""
    chosen: list[str] = []
    for part in parts:
        if chosen and em(sep.join([*chosen, part])) > limit:
            break
        chosen.append(part)
    return sep.join(chosen)


def pick(options: list[str], limit: float) -> str:
    for option in options:
        if em(option) <= limit:
            return option
    return min(options, key=em)


def superscript(number: int) -> str:
    return "".join(SUPERSCRIPTS[int(digit)] for digit in str(number))


WHOLE_UNIT_CURRENCIES = {"KRW": "원", "JPY": "엔"}
CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}


def money(amount: float, currency: str) -> str:
    """One currency format for every slide: cents for small amounts, whole units for large ones."""
    if currency in WHOLE_UNIT_CURRENCIES:
        return f"{round(amount):,}{WHOLE_UNIT_CURRENCIES[currency]}"
    prefix = CURRENCY_SYMBOLS.get(currency, currency + " ")
    if 0 < amount < 0.005:
        return f"{prefix}0.01 미만"
    return f"{prefix}{amount:,.0f}" if amount >= 1000 else f"{prefix}{amount:,.2f}"


def pct(ratio: float) -> str:
    """Whole-percent text that never rounds a partial result up to 100% (or a nonzero one down to 0%)."""
    value = ratio * 100
    if 99.5 <= value < 100:
        return f"{math.floor(value * 10) / 10:.1f}%"
    if 0 < value < 0.5:
        return f"{max(math.floor(value * 10) / 10, 0.1):.1f}%"
    return f"{ratio:.0%}"


_TRIGGERS = sorted(
    ((trigger, index) for index, (triggers, _label, _desc) in enumerate(GLOSSARY) for trigger in triggers),
    key=lambda row: -len(row[0]),
)
_PATTERN = re.compile("|".join(re.escape(trigger) for trigger, _index in _TRIGGERS))
_ENTRY = dict(_TRIGGERS)


def glossary_matches(text: str) -> list[tuple[int, int, int]]:
    """(start, end, glossary index) for every glossary term in the text, left to right."""
    return [(match.start(), match.end(), _ENTRY[match[0]]) for match in _PATTERN.finditer(text)]


def glossary_lines(indexes: list[int], first_number: int, limit: float) -> list[str]:
    """Pack '1) 용어 : 설명' entries into lines that stay inside the em limit."""
    entries = [
        f"{first_number + position}) {GLOSSARY[index][1]} : {GLOSSARY[index][2]}"
        for position, index in enumerate(indexes)
    ]
    lines: list[str] = []
    for entry in entries:
        if lines and em(lines[-1] + "   " + entry) <= limit:
            lines[-1] += "   " + entry
        else:
            lines.append(entry)
    return lines


@dataclass(frozen=True)
class Catalog:
    source: str
    months: tuple[tuple[int, int, int, int], ...]  # (year, month, total, built)
    partial_last: bool

    @property
    def total(self) -> int:
        return sum(row[2] for row in self.months)

    @property
    def built(self) -> int:
        return sum(row[3] for row in self.months)

    @property
    def first(self) -> int:
        return self.months[0][2]

    @property
    def last(self) -> int:
        return self.months[-1][2]

    @property
    def growth(self) -> float | None:
        return self.last / self.first if self.first else None


@dataclass(frozen=True)
class Usage:
    active: int
    idle: int
    unobserved: int
    provided: int  # platform-unidentified list packages (store apps included); not counted as agents


def monthly_counts(
    records: list[tuple[datetime, bool]], collected_at: datetime, months: int = 6,
) -> tuple[tuple[tuple[int, int, int, int], ...], bool]:
    """Six report months in KST (the report's own calendar): (year, month, total, built) per month.

    The last month is partial when the collection day is not the last day of that KST month.
    """
    def kst(value: datetime) -> datetime:
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(KST)

    end = kst(collected_at)
    window: list[tuple[int, int]] = []
    year, month = end.year, end.month
    for _ in range(months):
        window.append((year, month))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    window.reverse()
    local = [(kst(moment), built) for moment, built in records]
    rows = tuple(
        (y, m, sum(r[0].year == y and r[0].month == m for r in local),
         sum(r[0].year == y and r[0].month == m and r[1] for r in local))
        for y, m in window
    )
    return rows, end.day < calendar.monthrange(end.year, end.month)[1]


class DeckData:
    def __init__(
        self, assessment: Assessment, metrics: dict[str, ReportMetric] | None = None,
        collection: Collection | None = None, customer: str = DEFAULT_CUSTOMER,
        collected_at: datetime | None = None,
    ) -> None:
        self.assessment = assessment
        self.metrics = metrics or {}
        self.collection = collection
        self.customer = customer
        self.collected_at = collected_at or (collection.collected_at if collection else None)
        self.items = {item.code: item for item in assessment.system_items}
        self.scored = [item for item in self.items.values() if item.score is not None]
        self.passed = sum(item.score >= GAP_LEVEL for item in self.scored)
        self.pending = [item for item in self.items.values() if item.score is None]
        mode = self.metrics.get("run.mode")
        self.disclosure = (
            None if mode is not None and mode.value == "live"
            else "합성 데모 - 실제 진단 결과 아님" if mode is not None
            else "데이터 구분 미기록 - 출처 확인 필요"
        )

    @property
    def name(self) -> str:
        return "고객사" if self.customer == DEFAULT_CUSTOMER else self.customer

    # ---- primitives -------------------------------------------------------------------------
    def value(self, key: str) -> float | int | str | None:
        metric = self.metrics.get(key)
        return metric.value if metric is not None and metric.status == "observed" else None

    def rate(self, key: str) -> float | None:
        value = self.value(key)
        if value is None:
            return None
        if not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError("추가 보고서 충족률의 자료형·범위가 올바르지 않습니다.")
        return float(value)

    def score(self, code: str) -> int | None:
        item = self.items.get(code)
        return item.score if item else None

    def level(self, code: str) -> str:
        score = self.score(code)
        return f"L{score}" if score is not None else PENDING_LABEL

    def ratio(self, code: str) -> float | None:
        metric = self.metrics.get("se." + code)
        if metric is None or metric.status == "unavailable":
            return None
        if metric.unit != "ratio" or not isinstance(metric.value, (float, int)):
            raise ValueError("보고서 API 지표의 단위·자료형이 올바르지 않습니다.")
        return float(metric.value)

    def counts(self, code: str) -> tuple[float, float] | None:
        numerator = self.value(f"se.{code}.numerator")
        denominator = self.value(f"se.{code}.denominator")
        if isinstance(numerator, (int, float)) and isinstance(denominator, (int, float)) and denominator > 0:
            return float(numerator), float(denominator)
        return None

    def l3_min(self, code: str) -> float:
        value = self.value(f"se.{code}.l3_min")
        return float(value) if isinstance(value, (int, float)) and 0 <= value <= 1 else L3_FALLBACK

    def currency(self, code: str) -> str | None:
        """Currency code when the item is measured in money instead of counts."""
        metric = self.metrics.get(f"se.{code}.numerator")
        return metric.unit if metric is not None and metric.unit not in ("", "건") else None

    def amount_text(self, value: float, code: str) -> str:
        return money(value, self.currency(code) or "")

    def small_amount(self, code: str) -> bool:
        """A billed amount so small that its ratio is only a reference value."""
        pair, currency = self.counts(code), self.currency(code)
        if pair is None or currency is None:
            return False
        return pair[1] < (10000 if currency in WHOLE_UNIT_CURRENCIES else 10)

    def fraction(self, code: str) -> str | None:
        pair = self.counts(code)
        if pair is None:
            return None
        if self.currency(code):
            return f"{self.amount_text(pair[0], code)}/{self.amount_text(pair[1], code)}"
        return f"{pair[0]:g}/{pair[1]:g}"

    def metric_text(self, code: str) -> str:
        item = self.items.get(code)
        return item.metric if item and item.score is not None else "-"

    def catalog_owner_clause(self) -> str:
        if self.collection is None:
            return ""
        built = [p for p in self.collection.agent365_packages
                 if p.platform not in (None, "", BUILT_NOT_AVAILABLE)]
        if not built:
            return ""
        return f"소유자 지정 {sum((p.owner_count or 0) > 0 for p in built)}/{len(built)}"

    def percent(self, code: str) -> str | None:
        value = self.ratio(code)
        return None if value is None else pct(value)

    def advisory_state(self) -> tuple[int, int, int] | None:
        """Subscriptions with AI security advisories, waiting for them, and all subscriptions."""
        if self.collection is None:
            return None
        confirmed = {record.subscription_id for record in self.collection.security}
        waiting = {issue.subscription_id for issue in self.collection.issues
                   if issue.collector == "security"} - confirmed
        total = len(set(self.collection.subscriptions) | confirmed | waiting)
        return (len(confirmed), len(waiting), total) if total else None

    def pending_note(self, code: str) -> str:
        metric = self.metrics.get("se." + code)
        reason = metric.reason if metric and metric.reason else ""
        if code == "BI-SY-10" and self.collection and self.collection.copilot_agents:
            return "플랫폼별 보안 구성 증적 확인 후 판정"
        if code == "BI-SY-10" and reason in ("", "feature_unavailable", "not_found"):
            state = self.advisory_state()
            if state and state[1]:
                return f"보안 권고 {state[0]}개 구독 확인, {state[1]}개 구독 반영 대기"
        if code == "BI-SY-10" and reason not in ("", "feature_unavailable", "not_found"):
            return PENDING_BY_REASON.get(reason, "재조회 후 판정")
        if code in PENDING_BY_CODE:
            return PENDING_BY_CODE[code]
        return PENDING_BY_REASON.get(reason, "조회 범위 확인 후 판정")

    def pending_reason(self, code: str) -> str:
        """Short plain reason shown after '확인 중' in footnotes."""
        metric = self.metrics.get("se." + code)
        reason = metric.reason if metric and metric.reason else ""
        if code == "BI-SY-10" and self.collection and self.collection.copilot_agents:
            return "플랫폼별 보안 구성 증적 미확인"
        if code == "BI-SY-10" and reason in ("", "feature_unavailable", "not_found"):
            return "Defender 보안 권고 반영 대기"
        return PENDING_REASON_PLAIN.get(reason, "조회 범위 확인")

    def label(self, code: str) -> str:
        return LABELS.get(code) or (self.items[code].title if code in self.items else code)

    def _pattern(self, pattern: str, code: str) -> str:
        pair = self.counts(code)
        if pair is None:
            return ""
        numerator, denominator = pair
        if self.currency(code):
            return pattern.format(
                n=self.amount_text(numerator, code), d=self.amount_text(denominator, code),
                m=self.amount_text(max(denominator - numerator, 0), code),
            )
        return pattern.format(n=f"{numerator:g}", d=f"{denominator:g}", m=f"{denominator - numerator:g}")

    def fact(self, code: str, *, short: bool = True) -> str:
        """Business wording with the numbers; a pending item says it is being confirmed."""
        label = FACTS[code][0] if code in FACTS else self.label(code)
        if self.score(code) is None:
            return f"{label} 확인 중"
        row = FACTS.get(code)
        if row and code in AMOUNT_FACTS and self.currency(code):
            row = (row[0], *AMOUNT_FACTS[code], row[3])
        text = self._pattern(row[1 if short else 2], code) if row else ""
        if text and not short and self.counts(code) and self.counts(code)[0] == 0 and code in ZERO_LONG:
            text = self._pattern(ZERO_LONG[code], code)
        return text or f"{label} {self.level(code)}"

    def long_fact(self, code: str) -> str:
        return self.fact(code, short=False)

    def risk(self, code: str) -> str:
        return FACTS[code][3] if code in FACTS else ""

    def gap_line(self, code: str) -> str:
        """What the number means for the business, always as a possibility."""
        return f"{self.long_fact(code)} - {self.risk(code)}"

    def evidence(self, codes: tuple[str, ...], limit: int = 2, *, short: bool = True) -> list[str]:
        known = [code for code in codes if code in self.items]
        measured = sorted(
            (code for code in known if self.score(code) is not None),
            key=lambda code: (self.score(code), self.ratio(code) if self.ratio(code) is not None else 1,
                              known.index(code)),
        )
        parts = [self.fact(code, short=short) for code in measured[:limit]]
        waiting = [code for code in known if self.score(code) is None]
        if waiting:
            parts.append(self.fact(waiting[0], short=short))
        return parts

    def worst(self, codes: tuple[str, ...]) -> int | None:
        scores = [self.score(code) for code in codes if self.score(code) is not None]
        return min(scores) if scores else None

    def gaps(self, codes: tuple[str, ...]) -> list[str]:
        return [code for code in codes if code in self.items
                and self.score(code) is not None and self.score(code) < GAP_LEVEL]

    def worst_gap(self, codes: tuple[str, ...]) -> str | None:
        gaps = self.gaps(codes)
        if not gaps:
            return None
        return sorted(gaps, key=lambda c: (self.score(c), self.ratio(c) or 0, codes.index(c)))[0]

    def average(self, codes: tuple[str, ...]) -> float | None:
        scores = [self.score(code) for code in codes if self.score(code) is not None]
        return round1(sum(scores) / len(scores)) if scores else None

    @cached_property
    def conditional_access(self) -> tuple[int, int] | None:
        """Entra Agent IDs covered by an explicitly enabled conditional access target."""
        if self.collection is not None:
            for dataset in self.collection.report_evidence:
                if dataset.code == "OE-SY-30" and dataset.kind == "target_controls" and dataset.complete:
                    flags = [record.value for record in dataset.records if isinstance(record.value, bool)]
                    if flags:
                        return sum(flags), len(flags)
        return None

    # ---- overall -----------------------------------------------------------------------------
    @property
    def overall(self) -> float | None:
        return self.assessment.overall

    @property
    def provisional(self) -> bool:
        return self.assessment.overall_status != "6개 영역 집계"

    @property
    def overall_label(self) -> str:
        return PENDING_LABEL if self.overall is None else f"L{self.overall:.1f}"

    @property
    def target_gap(self) -> str:
        if self.overall is None:
            return "판정 대기"
        if self.overall >= TARGET_LEVEL:
            return "충족"
        return "근접했으나 미달" if TARGET_LEVEL - self.overall <= 0.3 else "미달"

    def collected_label(self) -> str:
        stamp = self.value("run.collected_at")
        moment = self.collected_at
        if isinstance(stamp, str):
            try:
                moment = datetime.fromisoformat(stamp)
            except ValueError:
                moment = self.collected_at
        if moment is None:
            return ""
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        moment = moment.astimezone(KST)
        return f"{moment.year}년 {moment.month}월 {moment.day}일"

    # ---- collection-derived views -------------------------------------------------------------
    @cached_property
    def catalog(self) -> Catalog | None:
        if self.collection is None or self.collection.collected_at is None:
            return None
        packages = [p for p in self.collection.agent365_packages if p.created_at is not None]
        records = [(p.created_at, p.platform not in (None, "", BUILT_NOT_AVAILABLE)) for p in packages]
        source = "Agent 365 목록"
        if not records:
            records = [(a.created_at, True) for a in self.collection.agents if a.created_at is not None]
            source = "Azure 에이전트 생성일"
        if not records:
            return None
        rows, partial = monthly_counts(records, self.collection.collected_at)
        if sum(row[2] for row in rows) == 0:
            return None
        return Catalog(source, rows, partial)

    @cached_property
    def usage(self) -> Usage | None:
        if self.collection is None or not self.collection.agent365_packages:
            return None
        packages = self.collection.agent365_packages
        built = [p for p in packages if p.platform not in (None, "", BUILT_NOT_AVAILABLE)]
        if not built:
            return None
        active = idle = 0
        for package in built:
            observed = (
                package.detail_complete and package.total_sessions_30d is not None
                and "total_sessions_30d" not in package.field_status
            )
            if not observed:
                continue
            if (package.total_sessions_30d or 0) > 0 or (package.active_users_30d or 0) > 0:
                active += 1
            else:
                idle += 1
        return Usage(active, idle, len(built) - active - idle, len(packages) - len(built))

    @cached_property
    def tools(self) -> list[str] | None:
        data = self.collection
        if data is None:
            return None
        facts = data.facts
        checks = (
            ("Microsoft Entra", data.entra_agent_identities or data.entra_blueprints),
            ("Microsoft Foundry", data.evaluations or data.deployments
             or any(agent.platform == "foundry" for agent in data.agents)),
            ("Azure Monitor", data.logs or facts.get("logs_complete_subscriptions")),
            ("Azure Policy", data.policy_assignments or facts.get("policies_complete_subscriptions")),
            ("Defender for Cloud", data.defender_plans or data.security or data.secure_scores),
            ("Power Platform", data.admin_evidence or data.copilot_agents),
            ("Agent 365", data.agent365_packages),
            ("Cost Management", data.budgets or data.costs),
        )
        return [name for name, present in checks if present]

    def subscriptions(self) -> int | None:
        value = self.value("scope.subscriptions")
        if isinstance(value, (int, float)):
            return int(value)
        return len(self.collection.subscriptions) if self.collection else None

    def azure_agents(self) -> int | None:
        value = self.value("inventory.azure")
        if isinstance(value, (int, float)):
            return int(value)
        return len(self.collection.agents) if self.collection else None

    # ---- grouping -----------------------------------------------------------------------------
    def groups(self) -> list[tuple[str, str, tuple[str, ...]]]:
        result = []
        for key in ("T1", "T2", "T3", "T4", "T5"):
            membership = self.metrics.get(f"group.{key}.codes")
            if membership is not None and membership.status == "observed":
                codes = tuple(str(membership.value).split(","))
                label = membership.label
            else:
                label, codes = DEFAULT_GROUPS[key]
            if len(set(codes)) != len(codes) or any(code not in self.items for code in codes):
                raise ValueError("보고서 유형 분류에 알 수 없거나 중복된 SY 코드가 있습니다.")
            result.append((key, label, codes))
        return result

    def band(self, level: str, fallback: str) -> str:
        text = self.value(f"criteria.{level}.text")
        if not isinstance(text, str):
            return fallback
        match = re.fullmatch(r"p=(\d+(?:\.\d+)?)%", text)
        if match:
            return f"충족 비율 {match[1]}%"
        match = re.fullmatch(r"(\d+(?:\.\d+)?)%<(=?)p<(\d+(?:\.\d+)?)%", text)
        if match:
            return f"충족 비율 {match[1]}% {'이상' if match[2] else '초과'}"
        return fallback

    # ---- interview vs evidence ---------------------------------------------------------------
    def corrected(self) -> list[str]:
        return [p for p, area in self.assessment.areas.items() if area.status == "인터뷰-실측 괴리"]

    def ahead(self) -> list[tuple[str, float]]:
        rows = [
            (prefix, round1(area.system - area.interview))
            for prefix, area in self.assessment.areas.items()
            if area.system is not None and area.interview is not None
            and area.system - area.interview >= AHEAD_MARGIN
        ]
        return sorted(rows, key=lambda row: -row[1])

    def weakest_perspective(self, prefixes: list[str]) -> str | None:
        averages = {}
        for kind, _label in KINDS[:4]:
            values = [self.assessment.areas[p].perspectives.get(kind) for p in prefixes]
            values = [v for v in values if v is not None]
            if values:
                averages[kind] = sum(values) / len(values)
        return PERSPECTIVES[min(averages, key=averages.get)] if averages else None

    def area_name(self, prefix: str) -> str:
        return next(row[3] for row in AREAS if row[0] == prefix)

    def area_label(self, prefix: str) -> str:
        return f"{self.area_name(prefix)} ({AREA_KO[prefix]})"

    # ---- roadmap ------------------------------------------------------------------------------
    def tasks(self) -> list[dict[str, object]]:
        """Roadmap rows: items below L3 or still being confirmed are tasks; L3 items only get an L4 step-up.

        An item at or above its own target is never listed with a target it already exceeds.
        """
        rows = []
        for order, (name, short, codes, owner, target) in enumerate(TASKS):
            known = tuple(code for code in codes if code in self.items)
            if not known:
                continue
            below = [code for code in known if self.score(code) is None or self.score(code) < GAP_LEVEL]
            at_target = [code for code in known if self.score(code) == GAP_LEVEL]
            if below:
                pending = [code for code in below if self.score(code) is None]
                worst = self.worst(tuple(below))
                phase = 1 if pending or worst is None or worst <= 1 else 2
                floor = max(self.l3_min(code) for code in known)
                title, label, codes_out = name, short, below
                measured = worst is not None and not pending
            elif at_target:
                phase, floor, worst, measured = 3, L4_FLOOR, GAP_LEVEL, True
                title, label, codes_out = f"L4 상향 : {name}", f"{short} L4 상향", at_target
            else:
                continue
            rows.append({
                "name": title, "short": label, "codes": codes_out, "owner": owner,
                "target": target.format(t=f"{floor:.0%} 이상"), "phase": phase, "order": order,
                "measured": measured, "worst": -1 if worst is None else worst, "floor": floor,
                "raise": not below,
            })
        rows.sort(key=lambda row: (row["phase"], not row["measured"], row["worst"], row["order"]))
        return rows

    def target_path(self) -> list[float] | None:
        if self.overall is None:
            return None
        goal = round1(max(TARGET_LEVEL, self.overall) + 0.3)
        return [round1(self.overall + (goal - self.overall) * step / 3) for step in (1, 2, 3)]

    def domains(self) -> list[dict[str, object]]:
        rows = []
        for order, (key, short, title, codes) in enumerate(DOMAINS):
            known = tuple(code for code in codes if code in self.items)
            if not known:
                continue
            rows.append({
                "key": key, "short": short, "title": title, "codes": known, "order": order,
                "owner": DOMAIN_OWNER[key], "level": self.average(known),
                "gaps": len(self.gaps(known)) + sum(self.score(code) is None for code in known),
            })
        rows.sort(key=lambda row: (row["level"] is None, row["level"] or 0, -row["gaps"], row["order"]))
        return rows
