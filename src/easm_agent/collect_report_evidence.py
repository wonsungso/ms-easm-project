"""Optional historical reads kept separate from current 26-control measurements."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from azure.core.exceptions import ClientAuthenticationError

from easm_agent.azure import AccessError, Credential, EvidenceStore, ReaderHTTP, issue
from easm_agent.collect_signals import SignalCollector
from easm_agent.models import Collection, CostHistoryEvidence, HistoricalCostRecord, Issue, Settings
from easm_agent.report_evidence import _months


def collect_cost_history(
    credential: Credential, data: Collection, settings: Settings,
    store: EvidenceStore, now: datetime, criteria: dict,
) -> Collection:
    months = criteria.get("report_options", {}).get("history_months")
    if type(months) is not int or not 1 <= months <= 12:
        raise ValueError("비용 이력에는 report_options.history_months 1~12가 필요합니다.")
    start = _months(now, months)[0]

    def subscription(sid: str) -> tuple[list[HistoricalCostRecord], list[Issue], set[str]]:
        http = ReaderHTTP(credential, store=store, subscription=sid)
        records: list[HistoricalCostRecord] = []
        failures: list[Issue] = []
        refs: set[str] = set()
        try:
            collector = SignalCollector(http, data, now, criteria, settings.monitor, data.subscriptions)
            if not collector.ai_ids(sid):
                return [], [], set()
            incoming = Collection(collected_at=now)
            collector.costs(sid, incoming, start=start)
            for row in incoming.costs:
                usage_date = row.usage_date
                if usage_date is None:
                    raise ValueError("비용 사용일이 없습니다.")
                date = datetime.strptime(usage_date, "%Y%m%d").replace(tzinfo=UTC)
                if not start <= date < now:
                    raise ValueError("비용 사용일이 요청 기간 밖에 있습니다.")
                identifier = hashlib.sha256(
                    (row.resource_id.lower() + ":" + usage_date + ":" + row.currency).encode(),
                ).hexdigest()
                records.append(HistoricalCostRecord(
                    subject="cost-" + identifier, evidence_ids=[row.resource_id],
                    occurred_at=date, amount=row.amount, currency=row.currency,
                    # Current inventory does not prove a historical cost allocation.
                    attributed_amount=None,
                ))
                refs.update(row.evidence_refs)
        except AccessError as exc:
            failures.append(issue(http, "report_cost_history", sid, exc, ("Cost Management Reader",)))
        except (ValueError, KeyError, TypeError, ClientAuthenticationError) as exc:
            failures.append(issue(
                http, "report_cost_history", sid,
                AccessError("permission_denied" if isinstance(exc, ClientAuthenticationError) else "error",
                            "비용 이력 처리 실패: " + type(exc).__name__ + " - 원문·토큰 미출력"),
                ("Cost Management Reader",),
            ))
        finally:
            if http.last_ref:
                refs.add(http.last_ref)
            http.close()
        return records, failures, refs

    records: list[HistoricalCostRecord] = []
    failures: list[Issue] = []
    refs: set[str] = set()
    with ThreadPoolExecutor(max_workers=settings.workers) as executor:
        for rows, issues, sources in executor.map(subscription, data.subscriptions):
            records.extend(rows)
            failures.extend(issues)
            refs.update(sources)
    if not records and not failures:
        failures.append(Issue(
            collector="report_cost_history", target="OT-SY-34", reason="not_found",
            detail="조회 대상 Azure AI 리소스·실제 비용 행 없음. 과거 삭제 리소스는 현재 인벤토리로 복원하지 않음",
        ))
    reason = failures[0].reason if failures else None
    result = Collection(collected_at=now, issues=failures, report_evidence=[CostHistoryEvidence(
        kind="cost_history", code="OT-SY-34", source_kind="official_admin_read",
        source_ref="azure-costmanagement-2023-03-01",
        scope="현재 발견된 Azure AI 리소스의 비용 이력. 과거 삭제 리소스·과거 Agent 귀속·M365 청구 제외",
        observed_at=now, period_start=start, period_end=now, complete=not failures,
        population_complete=not failures and data.facts.get("agent_inventory_complete") is True,
        reason=reason, records=records,
        evidence_refs=sorted(refs),
    )])
    return result
