from __future__ import annotations

import argparse
import contextlib
import json
import logging
import re
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import DefaultAzureCredential

from easm_agent.azure import AccessError, EvidenceStore
from easm_agent.collect import collect, merge
from easm_agent.collect_admin_evidence import read_admin_evidence
from easm_agent.collect_copilot import read_copilot_inventory
from easm_agent.collect_entra import EntraCollector
from easm_agent.evaluation import evaluate
from easm_agent.models import (
    Collection,
    Finding,
    load_conventions,
    load_criteria,
    load_settings,
)
from easm_agent.proposals import evaluate_proposals
from easm_agent.report import latest_raw, load_result, write_reports
from easm_agent.report_backdata import metrics_by_key
from easm_agent.report_evidence import read_report_evidence
from easm_agent.report_excel import refresh_interview_summary
from easm_agent.report_pptx import DEFAULT_CUSTOMER, context_from_workbook, write_presentation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="읽기 전용 Azure/Foundry 거버넌스 증적")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("collect")
    command.add_argument("--config", type=Path, default=Path("config") / "custom-config.yaml",
                         help="고객별 선택 설정 파일")
    command.add_argument("--criteria", type=Path, help="등급 기준 YAML 경로 - 기본값 config/criteria.yaml")
    command.add_argument("--setup-file", type=Path)
    scope = command.add_mutually_exclusive_group()
    scope.add_argument("--subscriptions", nargs="+")
    scope.add_argument(
        "--all-subscriptions", action="store_true",
        help="설정 구독 목록 대신 지정 테넌트에서 진단 계정이 접근 가능한 모든 활성 구독 수집",
    )
    command.add_argument("--tenant-id")
    command.add_argument("--expected-principal-id")
    command.add_argument("--manual-agents", type=Path)
    command.add_argument("--admin-evidence-file", action="append", type=Path, default=[])
    command.add_argument("--copilot-inventory-file", action="append", type=Path, default=[])
    command.add_argument("--report-evidence-file", action="append", type=Path, default=[])
    command.add_argument("--report-cost-history", action="store_true", help="현재 Azure AI 리소스의 과거 비용 읽기 - 과거 Agent 귀속은 추론하지 않음")
    command.add_argument(
        "--copilot-only", action="store_true",
        help="Azure/Graph 호출 없이 승인된 Copilot 인벤토리 파일만 보고서로 생성",
    )
    command.add_argument(
        "--agent365-registry", action="store_true",
        help="선택적 Microsoft Agent365 등록부 읽기 - 별도 권한 및 라이선스 필요",
    )
    command.add_argument("--output-dir", type=Path, default=Path("output"))
    command.add_argument("--fixture", type=Path)
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--customer", default=DEFAULT_CUSTOMER, help="PPT 표지의 고객사명")
    package = subparsers.add_parser("package", help="raw-data-<타임스탬프>.json을 읽어 Excel·PPT 보고서 재생성")
    package.add_argument("--output-dir", type=Path, default=Path("output"))
    package.add_argument("--customer", default=DEFAULT_CUSTOMER, help="PPT 표지의 고객사명")
    package.add_argument("--mode", choices=["live", "fixture"])
    package.add_argument("--admin-evidence-file", action="append", type=Path, default=[])
    package.add_argument("--copilot-inventory-file", action="append", type=Path, default=[])
    package.add_argument("--report-evidence-file", action="append", type=Path, default=[])
    package.add_argument("--tenant-id")
    package.add_argument(
        "--reassess", action="store_true",
        help="저장된 실측 데이터를 현재 기준으로 다시 평가하고 새 API 수집이 아님을 기록",
    )
    package.add_argument("--config", type=Path, default=Path("config") / "custom-config.yaml",
                         help="재평가에 사용할 고객별 선택 설정 파일")
    package.add_argument("--criteria", type=Path, help="재평가 기준 YAML 경로 - 기본값 config/criteria.yaml")
    deck = subparsers.add_parser(
        "deck", help="인터뷰 점수를 기입한 Excel 보고서에서 PPT 보고서(EASM-report-<타임스탬프>.pptx) 생성",
    )
    deck.add_argument("--output-dir", type=Path, default=Path("output"), help="실행 폴더 또는 그 상위 output 폴더")
    deck.add_argument("--workbook", type=Path, help="기입이 끝난 Excel 보고서 - 기본값은 실행 폴더의 report-*.xlsx")
    deck.add_argument("--customer", default=DEFAULT_CUSTOMER, help="PPT 표지의 고객사명")
    args = parser.parse_args(argv)
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("azure.identity").setLevel(logging.ERROR)
    scratch = contextlib.ExitStack()
    try:
        if args.command == "deck":
            source = latest_raw(args.output_dir)
            if source is None:
                raise ValueError("수집 결과 raw-data JSON을 찾을 수 없습니다.")
            stamp = source.stem.removeprefix("raw-data-")
            workbook = args.workbook or source.parent / f"report-{stamp}.xlsx"
            if not workbook.is_file():
                raise FileNotFoundError(f"Excel 보고서를 찾을 수 없습니다: {workbook}")
            result = load_result(source.parent)
            refresh_interview_summary(
                workbook, Collection.model_validate(result["collection"]),
                [Finding.model_validate(row) for row in result["findings"]],
            )
            deck_path = source.parent / f"EASM-report-{stamp}.pptx"
            collection = Collection.model_validate(result["collection"])
            findings = [Finding.model_validate(row) for row in result["findings"]]
            mode = result.get("mode") or collection.facts.get("data_mode") or "live"
            write_presentation(workbook, deck_path, context_from_workbook(
                workbook, args.customer, metrics_by_key(collection, findings, mode), collection,
            ))
            print(f"PPT 보고서: {deck_path}")
            return 0
        if args.command == "package":
            source = latest_raw(args.output_dir)
            if source is None:
                raise ValueError("수집 결과 raw-data JSON을 찾을 수 없습니다.")
            result = load_result(source.parent)
            data = Collection.model_validate(result["collection"])
            findings = [Finding.model_validate(row) for row in result["findings"]]
            recorded_mode = result.get("mode") or data.facts.get("data_mode")
            if recorded_mode and args.mode and recorded_mode != args.mode:
                raise ValueError("수집한 데이터 구분과 지정한 mode가 다릅니다.")
            mode = recorded_mode or args.mode
            if mode not in ("live", "fixture"):
                raise ValueError("기존 파일의 데이터 구분이 없습니다. --mode live 또는 --mode fixture를 명시하세요.")
            if args.admin_evidence_file:
                if mode != "live":
                    raise ValueError("실제 관리자 증적은 fixture 결과에 혼합하지 않습니다.")
                tenants = {str(uuid.UUID(agent.tenant_id)) for agent in data.agents if agent.tenant_id}
                if args.tenant_id:
                    tenants.add(str(uuid.UUID(args.tenant_id)))
                if len(tenants) != 1:
                    raise ValueError("관리자 증적 반영에는 단일 수집 테넌트 확인이 필요합니다.")
                tenant = tenants.pop()
                recorded_directory = data.facts["evidence_directory"]
                if recorded_directory == "embedded:evidence":
                    # Attached evidence is embedded in the raw JSON, so keep it out of the run folder.
                    directory = Path(scratch.enter_context(tempfile.TemporaryDirectory(prefix="easm-evidence-")))
                else:
                    directory = Path(recorded_directory)
                    if not directory.is_dir():
                        raise FileNotFoundError("기존 증적 보관 경로가 없어 관리자 내보내기를 첨부할 수 없습니다.")
                store = EvidenceStore(directory)
                data.facts["evidence_directory"] = str(directory.resolve())
                seen_sources: set[str] = set()
                for path in args.admin_evidence_file:
                    incoming = read_admin_evidence(path, tenant, datetime.now(UTC), store)
                    sources = {read.source for read in incoming.admin_evidence}
                    if seen_sources & sources:
                        raise ValueError("같은 관리자 조회 원천을 중복 반영할 수 없습니다.")
                    seen_sources.update(sources)
                    data.admin_evidence = [read for read in data.admin_evidence if read.source not in sources]
                    data.admin_evidence.extend(incoming.admin_evidence)
            if args.report_evidence_file and not args.reassess:
                raise ValueError("추가 보고서 증적 첨부에는 --reassess로 현재 기준 출처를 기록해야 합니다.")
            if args.copilot_inventory_file or args.report_evidence_file:
                if mode != "live" or not args.tenant_id:
                    raise ValueError("Copilot 첨부에는 live 결과와 명시적 단일 --tenant-id가 필요합니다.")
                tenant = str(uuid.UUID(args.tenant_id))
                tenants = {
                    str(uuid.UUID(agent.tenant_id)) for agent in data.agents if agent.tenant_id
                } | {
                    str(uuid.UUID(value))
                    for value in data.facts.get("copilot_inventory_tenant_ids", [])
                } | {
                    str(uuid.UUID(value))
                    for value in data.facts.get("report_evidence_tenant_ids", [])
                } | {tenant}
                if len(tenants) != 1:
                    raise ValueError("Copilot 첨부 대상 수집 테넌트가 일치하지 않습니다.")
                recorded_directory = data.facts.get("evidence_directory")
                if recorded_directory == "embedded:evidence":
                    directory = source.parent / "evidence"
                    directory.mkdir(exist_ok=True)
                elif recorded_directory and Path(recorded_directory).is_dir():
                    directory = Path(recorded_directory)
                else:
                    raise FileNotFoundError("기존 증적 보관 경로가 없습니다.")
                store = EvidenceStore(directory)
                data.facts["evidence_directory"] = str(directory.resolve())
                for path in args.copilot_inventory_file:
                    merge(data, read_copilot_inventory(path, tenant, datetime.now(UTC), store))
                for path in args.report_evidence_file:
                    merge(data, read_report_evidence(path, tenant, datetime.now(UTC), store))
                data.evidence_sources.extend(store.sources())
            data.facts["data_mode"] = mode
            if args.reassess:
                settings = load_settings(args.config)
                if args.criteria:
                    settings.criteria_file = args.criteria
                criteria = load_criteria(settings)
                conventions = load_conventions(settings)
                data.proposals = [
                    proposal for proposal in data.proposals
                    if not (proposal.evidence_only and proposal.code in criteria["items"])
                ]
                findings = evaluate(
                    data, criteria, conventions,
                    interviews={row.se_code: row.interview_level for row in findings if row.interview_level is not None},
                    provenance_origin="saved_snapshot_reassessment",
                )
                data.assessment_provenance.source_result_data_sha256 = result.get("manifest", {}).get("data_sha256")
            write_reports(data, findings, source.parent, mode, new_run=False, customer=args.customer)
            return 0
        settings = load_settings(args.config)
        if args.admin_evidence_file:
            settings.admin_evidence_files = args.admin_evidence_file
        if args.copilot_inventory_file:
            settings.copilot_inventory_files = args.copilot_inventory_file
        if args.report_evidence_file:
            settings.report_evidence_files = args.report_evidence_file
        if args.report_cost_history:
            settings.report_cost_history = True
        if settings.report_cost_history and (args.fixture or args.copilot_only):
            raise ValueError("Azure 비용 이력 읽기는 --fixture 또는 --copilot-only와 함께 사용할 수 없습니다.")
        if args.fixture and settings.report_evidence_files:
            raise ValueError("실제 추가 보고서 증적은 fixture 수집에 혼합하지 않습니다.")
        if args.agent365_registry:
            settings.agent365_registry = True
        if settings.agent365_registry and (args.copilot_only or args.fixture):
            raise ValueError("Agent 365 등록부 API는 --copilot-only 또는 --fixture와 함께 사용할 수 없습니다.")
        if args.copilot_only and args.fixture:
            raise ValueError("--copilot-only와 --fixture는 함께 사용할 수 없습니다.")
        if args.fixture and settings.copilot_inventory_files:
            raise ValueError("실제 Copilot 인벤토리는 fixture 수집에 혼합하지 않습니다.")
        if args.fixture and settings.admin_evidence_files:
            raise ValueError("실제 관리자 증적은 fixture 수집에 혼합하지 않습니다.")
        if args.config != Path("config") / "custom-config.yaml" and not args.config.is_file():
            raise FileNotFoundError(f"선택 설정 파일을 찾을 수 없습니다: {args.config}")
        if args.criteria:
            settings.criteria_file = args.criteria
        setup_subscriptions: list[str] = []
        if args.setup_file:
            setup = json.loads(args.setup_file.read_text(encoding="utf-8-sig"))
            settings.tenant_id = setup["tenant_id"]
            settings.expected_principal_id = setup["principal_id"]
            setup_subscriptions = setup.get("subscription_ids") or []
        if args.tenant_id:
            settings.tenant_id = args.tenant_id
        if args.expected_principal_id:
            settings.expected_principal_id = args.expected_principal_id
        if args.subscriptions:
            settings.subscriptions = args.subscriptions
        elif args.all_subscriptions:
            settings.subscriptions = []
        elif setup_subscriptions:
            settings.subscriptions = setup_subscriptions
        if args.manual_agents:
            settings.manual_agents = args.manual_agents
        settings = type(settings).model_validate(settings.model_dump())
        if args.copilot_only and (not settings.tenant_id or not settings.copilot_inventory_files):
            raise ValueError("--copilot-only에는 tenant_id와 Copilot 인벤토리 파일이 필요합니다.")
        criteria = load_criteria(settings)
        if args.dry_run:
            print(json.dumps({
                "mode": "fixture" if args.fixture else "live",
                "tenant_id": settings.tenant_id,
                "subscriptions": "not_requested" if args.copilot_only else (
                    settings.subscriptions or "auto-enumerate"
                ),
                "output_dir": str(args.output_dir),
                "foundry_profile": settings.foundry_profile,
                "roles": [] if args.copilot_only else [
                    "Reader", "Cost Management Reader", "Log Analytics Reader", "Security Reader",
                    "Foundry: agents/read, evaluations/read, assets/read",
                ]
                + ["Graph: " + ", ".join(EntraCollector.required_roles)]
                + (["Graph: CopilotPackages.Read.All"] if settings.agent365_registry else []),
                "entra": not args.copilot_only,
                "azure_calls": False,
                **({"copilot_only": True} if args.copilot_only else {}),
                **({"agent365_registry": True} if settings.agent365_registry else {}),
            }, ensure_ascii=False, indent=2))
            return 0
        if args.copilot_only:
            instant = datetime.now(UTC)
            store = EvidenceStore(settings.evidence_dir, instant)
            data = Collection(collected_at=instant, facts={"copilot_only": True})
            for path in settings.copilot_inventory_files:
                merge(data, read_copilot_inventory(path, settings.tenant_id, instant, store))
            for path in settings.report_evidence_files:
                merge(data, read_report_evidence(path, settings.tenant_id, instant, store))
            data.facts["evidence_directory"] = str(store.path.resolve())
            data.evidence_sources = store.sources()
        elif args.fixture:
            data = Collection.model_validate_json(args.fixture.read_text(encoding="utf-8"))
            for agent in data.agents:
                agent.mark_unknowns()
        else:
            with DefaultAzureCredential() as credential:
                data = collect(settings, credential)
            data.facts["subscription_scope"] = (
                "explicit_subscription_list" if settings.subscriptions else "all_accessible_active_in_tenant"
            )
        data.facts["data_mode"] = "fixture" if args.fixture else "live"
        data.proposals = evaluate_proposals(data, load_conventions(settings))
        findings = evaluate(
            data, criteria,
            load_conventions(settings), settings.policy_facts, settings.interview_levels,
        )
        workbook = write_reports(data, findings, args.output_dir, "fixture" if args.fixture else "live",
                                 customer=args.customer)
        print(f"수집 완료: 구독={len(data.subscriptions)}, Agent/후보={len(data.agents)}, "
              f"Copilot={len(data.copilot_agents)}, 이슈={len(data.issues)}, 결과={workbook.parent}")
        return 2 if data.issues else 0
    except (ValueError, KeyError, TypeError, OSError, AccessError, ClientAuthenticationError) as exc:
        detail = str(exc) if isinstance(exc, AccessError) else type(exc).__name__
        if isinstance(exc, ClientAuthenticationError):
            code = re.search(r"AADSTS\d+", str(exc))
            if code:
                detail += " (" + code.group(0) + ")"
        print(f"실행 중단: {detail}. 원문·비밀값·토큰은 출력하지 않았습니다.", file=sys.stderr)
        return 1
    finally:
        scratch.close()


if __name__ == "__main__":
    raise SystemExit(main())
