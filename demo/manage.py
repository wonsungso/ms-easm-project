from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from azure.core.exceptions import AzureError
from openai import OpenAIError

from demo import defender, studio
from demo.auth import TemporaryCertificate
from demo.infrastructure import deploy, deployment_parameters, expected_agent_count, plan
from demo.saas import SaaSError, deploy_saas, load_verified_saas_receipt, preflight_saas
from easm_agent.azure import redact
from easm_agent.models import load_yaml
from easm_agent.paths import state_path
from easm_agent.report import load_result
from scripts.setup_account import ROLES, AzureCLI, ensure_assignment, ensure_graph_roles


def validate(cli: Any, setup: dict, options: dict, root: Path, prepare_providers: bool) -> int:
    preflight_saas(options, setup, root)
    proof: dict[str, Any] = {
        "passed": False, "checked_at": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0], "recipe": "AZCLI with Bicep",
        "checks": [],
    }
    proof_path = state_path(root, "demo", "validation.json")
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    for command in [
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "-m", "ruff", "check", "src", "scripts", "demo", "tests"],
    ]:
        completed = subprocess.run(command, cwd=root, check=False)
        if completed.returncode:
            raise RuntimeError("배포 전 로컬 검증 실패. Azure 배포를 시작하지 않습니다.")
        proof["checks"].append({"command": command[1:], "status": "passed"})
    context = cli.run("account", "show")
    if context["tenantId"].lower() != setup["tenant_id"]:
        raise ValueError("배포 전 관리자 테넌트 불일치")
    lab = plan(setup, options)
    cli.run("bicep", "build", "--file", str(root / "demo" / "main.bicep"), "--stdout")
    proof["checks"].append({"command": "az bicep build --stdout", "status": "passed"})
    for index, group in enumerate(lab["groups"]):
        sid = group["subscription_id"]
        print(f"배포 전 ARM 검증: 구독 {index + 1}/{len(lab['groups'])}", flush=True)
        namespace = "Microsoft.CognitiveServices"
        providers = cli.run("provider", "list", "--subscription", sid)
        # PolicyInsights는 정책 준수 상태를 읽는 수집 단계에 필요하다.
        required_providers = ("Microsoft.Resources", namespace, "Microsoft.OperationalInsights", "Microsoft.Insights")
        if index == 0:
            required_providers += ("Microsoft.PolicyInsights",)
        for required in required_providers:
            state = next((entry["registrationState"] for entry in providers
                          if entry["namespace"].lower() == required.lower()), None)
            if state != "Registered":
                if not prepare_providers:
                    raise RuntimeError(f"필요 공급자 {required} 미등록. --prepare-providers로 승인된 준비를 실행하세요.")
                cli.run("provider", "register", "--namespace", required, "--subscription", sid, "--wait")
        policies = cli.run("policy", "assignment", "list", "--scope", "/subscriptions/" + sid,
                           "--subscription", sid)
        parameters = deployment_parameters(lab, index)
        common = [
            "--subscription", sid, "--location", lab["region"],
            "--template-file", str(root / "demo" / "main.bicep"),
            "--parameters", *parameters,
        ]
        for attempt in range(3):
            try:
                cli.run("deployment", "sub", "validate", *common)
                preview = cli.run("deployment", "sub", "what-if", "--no-pretty-print", *common)
                break
            except RuntimeError as exc:
                if attempt == 2:
                    raise RuntimeError(f"구독 {index + 1}/3 ARM 검증 실패: {exc}") from exc
                time.sleep(10)
        if any(change.get("changeType") == "Delete" for change in (preview or {}).get("changes", [])):
            raise RuntimeError("what-if에 삭제가 포함되어 있습니다. 샘플 유지 승인 범위를 넘어 중단합니다.")
        proof["checks"].append({
            "subscription_id": sid, "template_validate": "passed", "what_if": "passed",
            "policy_assignments_retrieved": len(policies), "destructive_preview": False,
        })
        proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    proof["passed"] = True
    proof["finished_at"] = datetime.now(UTC).isoformat()
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print("배포 전 검증 통과: Python/Bicep/Foundry 배포 구독 validate·what-if·정책 조회", flush=True)
    return 0


ROOT = Path(__file__).resolve().parents[1]


def lab_config_path(root: Path) -> Path:
    override = os.environ.get("EASM_AGENT_LAB_CONFIG")
    if override is None:
        return root / "demo" / "config.yaml"
    path = Path(override)
    if not path.is_absolute():
        raise ValueError("EASM_AGENT_LAB_CONFIG에는 절대 경로가 필요합니다.")
    return path


def cleanup_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="별도 승인 후 실행하는 샘플 전용 정리. 기본값은 dry-run.")
    parser.add_argument("--setup-file", type=Path, default=state_path(ROOT, "setup.json"))
    parser.add_argument("--lab-config", type=Path, default=lab_config_path(ROOT))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-lab-id")
    args = parser.parse_args(argv)
    setup = json.loads(args.setup_file.read_text(encoding="utf-8-sig"))
    lab = plan(setup, load_yaml(args.lab_config))
    if args.apply and args.confirm_lab_id != lab["lab_id"]:
        raise ValueError("삭제에는 정확한 --confirm-lab-id가 필요합니다. 자동 삭제하지 않습니다.")
    cli = AzureCLI()
    if cli.run("account", "show")["tenantId"].lower() != setup["tenant_id"]:
        raise ValueError("정리 관리자 테넌트 불일치")
    verified = []
    for group in lab["groups"]:
        existing = next((row for row in cli.run("group", "list", "--subscription", group["subscription_id"])
                         if row["name"].lower() == group["name"].lower()), None)
        if not existing:
            print(f"이미 없는 샘플 그룹: {group['name']}")
            continue
        if (existing.get("tags") or {}).get("easmagent-lab") != lab["lab_id"]:
            raise ValueError("소유 태그가 다릅니다. 어떤 그룹도 삭제하지 않았습니다.")
        verified.append(group)
    for group in verified:
        print(f"{'DELETE' if args.apply else 'DRY-RUN'}: {group['id']}")
        if args.apply:
            cli.run("group", "delete", "--name", group["name"],
                    "--subscription", group["subscription_id"], "--yes")
            remaining = cli.run("group", "list", "--subscription", group["subscription_id"])
            if any(row["name"].lower() == group["name"].lower() for row in remaining):
                raise RuntimeError("삭제 명령 후에도 샘플 그룹이 남아 있습니다.")
            print(f"삭제 완료 재확인: {group['name']}")
    if args.apply:
        state = state_path(ROOT, "demo")
        state.mkdir(parents=True, exist_ok=True)
        proof = {
            "lab_id": lab["lab_id"], "deleted_at": datetime.now(UTC).isoformat(),
            "groups": [group["id"] for group in verified],
            "diagnostic_account_retained": True, "codespaces_retained": True,
        }
        (state / "cleanup.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
        existing_lab = state / "lab.json"
        if existing_lab.is_file():
            saved = json.loads(existing_lab.read_text(encoding="utf-8"))
            if saved.get("lab_id") == lab["lab_id"]:
                saved["resources_deleted"] = True
                saved["deleted_at"] = proof["deleted_at"]
                existing_lab.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def save(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def child(command: list[str], environment: dict[str, str] | None = None) -> int:
    return subprocess.run([sys.executable, *command], cwd=ROOT, env=environment, check=False).returncode


def offline() -> None:
    if child(["-m", "pytest", "-q"]):
        raise RuntimeError("오프라인 테스트 실패; Azure 샘플 배포를 시작하지 않습니다.")
    if child(["-m", "easm_agent.cli", "collect", "--fixture", "tests/fixtures/three_subscriptions.json",
              "--output-dir", str(state_path(ROOT, "mock"))]):
        raise RuntimeError("오프라인 fixture Run-through 실패")


def collect_live(
    setup: dict, lab: dict, cli: AzureCLI, options: dict, skip_graph_roles: bool = False,
    *, persist_lab: bool = True,
) -> int:
    if lab.get("resources_deleted"):
        raise ValueError("데모 리소스가 삭제된 상태입니다. 먼저 데모를 다시 배포하세요.")
    agent365_registry = options.get("agent365_registry", False)
    if type(agent365_registry) is not bool:
        raise ValueError("agent365_registry는 true 또는 false여야 합니다.")
    settings: dict = {
        "tenant_id": setup["tenant_id"], "expected_principal_id": setup["principal_id"],
        "subscriptions": setup["subscription_ids"],
        "evidence_dir": str(state_path(ROOT, "evidence")),
        "projects": [{"subscription_id": setup["subscription_ids"][0],
                      "resource_id": lab["project_id"], "endpoint": lab["project_endpoint"]}],
        "allowed_models": [{"name": lab["model"], "version": lab["model_version"]}],
        "report_cost_history": True, "agent365_registry": agent365_registry,
    }
    admin_files = options.get("admin_evidence_files", [])
    if not isinstance(admin_files, list) or not all(isinstance(item, str) and item for item in admin_files):
        raise ValueError("admin_evidence_files는 승인된 내보내기 경로 목록이어야 합니다.")
    if admin_files:
        settings["admin_evidence_files"] = admin_files
    state = state_path(ROOT, "demo")
    state.mkdir(parents=True, exist_ok=True)
    if "saas" in options:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        for script, key, suffix, extra in (
            ("export_copilot_inventory.py", "copilot_inventory_files", "copilot", ["--include-evaluations"]),
            ("export_report_evidence.py", "report_evidence_files", "conditional-access", ["--conditional-access"]),
        ):
            if script == "export_copilot_inventory.py" and options.get("copilot_evaluation_cli"):
                extra = [
                    *extra, "--evaluation-cli", options["copilot_evaluation_cli"],
                    "--evaluation-project", options["copilot_evaluation_project"],
                ]
            export_path = state / f"{suffix}-{stamp}.json"
            status = child([
                str(ROOT / "scripts" / script), "--tenant-id", setup["tenant_id"],
                "--approved", "--output", str(export_path), *extra,
            ])
            if status not in (0, 2) or not export_path.is_file():
                raise RuntimeError("별도 관리자 증적 내보내기 실패; 진단 SP·수동 값으로 대체하지 않음")
            settings[key] = [str(export_path)]
        for script, extra in (
            ("export_admin_environments.py", []),
            ("export_dlp_policies.py", ["--approved"]),
        ):
            export_path = state / f"{script.removesuffix('.py')}-{stamp}.json"
            status = child([
                str(ROOT / "scripts" / script), "--tenant-id", setup["tenant_id"],
                "--output", str(export_path), *extra,
            ])
            if status not in (0, 2) or not export_path.is_file():
                raise RuntimeError("관리자 환경·DLP API 내보내기 실패")
            settings.setdefault("admin_evidence_files", []).append(str(export_path))
    config_path = state / "lab-collection.yaml"
    config_path.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")
    projects_path = state / "lab-projects.json"
    save(projects_path, settings["projects"])
    with TemporaryCertificate(setup) as environment:
        command = ["-m", "easm_agent.cli", "collect", "--config", str(config_path),
                   "--output-dir", str(ROOT / "output")]
        if options.get("collect_all_subscriptions"):
            command.append("--all-subscriptions")
        if not skip_graph_roles:
            ensure_graph_roles(cli, setup["principal_id"])
            time.sleep(30)
        code = child(command, environment)
        if code == 1:
            time.sleep(15)
            code = child(command, environment)
        if code not in (0, 2):
            raise RuntimeError("진단 SP 수집 실행 실패; 관리자 수집으로 대체하지 않음")
        collection = load_result(ROOT / "output")["collection"]
        changes = []
        if options.get("auto_grant_needed_read_roles"):
            for entry in collection["issues"]:
                if entry["reason"] != "permission_denied" or "HTTP 403" not in entry["detail"]:
                    continue
                if entry["collector"] == "agent_usage":
                    scope, role = lab["workspace_id"], "Log Analytics Reader"
                elif entry["collector"] == "cost":
                    scope = "/subscriptions/" + entry["subscription_id"]
                    role = "Cost Management Reader"
                else:
                    continue
                record = {"scope": scope, "role": role}
                if record not in changes:
                    ensure_assignment(cli, setup["principal_id"], "ServicePrincipal", scope, ROLES[role])
                    changes.append(record)
            if changes:
                time.sleep(30)
                code = child(command, environment)
                if code not in (0, 2):
                    raise RuntimeError("제한된 추가 읽기 역할 적용 후 수집 실행 실패")
        lab["additional_diagnostic_read_roles"] = changes
        if persist_lab:
            save(state / "lab.json", lab)
        preflight = child([
            "scripts/verify_permissions.py", "--tenant-id", setup["tenant_id"],
            "--expected-principal-id", setup["principal_id"],
            "--subscriptions", *setup["subscription_ids"], "--projects-file", str(projects_path),
        ], environment)
        if preflight not in (0, 2):
            raise RuntimeError("진단 SP 접근 사전 점검 실행 실패")
    collection = load_result(ROOT / "output")["collection"]
    expected = expected_agent_count(lab)
    if len(collection["agents"]) < expected or len(collection["completed_subscriptions"]) != 3:
        raise RuntimeError(f"승인된 3개 구독/{expected}개 Agent 샘플의 실측 발견을 확인하지 못했습니다.")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="관리자 샘플 준비와 진단 Reader Run-through 분리 실행")
    parser.add_argument("command", choices=[
        "plan", "test", "validate", "deploy", "saas", "defender", "studio-publish", "collect", "all", "cleanup",
    ])
    parser.add_argument("--revert", action="store_true", help="defender 명령에서 기록된 플랜 상태로 복원")
    parser.add_argument(
        "--skip-graph-roles", action="store_true",
        help="collect에서 진단 SP의 Graph 앱 역할 재확인을 생략 - 관리자 Graph 토큰을 쓸 수 없고 역할이 이미 검증된 경우",
    )
    parser.add_argument("--setup-file", type=Path, default=state_path(ROOT, "setup.json"))
    parser.add_argument("--lab-config", type=Path, default=lab_config_path(ROOT))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--prepare-providers", action="store_true")
    parser.add_argument("--reuse-infrastructure", action="store_true")
    parser.add_argument("--reconcile", action="store_true", help="실패한 SaaS 배포를 클라우드 읽기로만 재검증")
    parser.add_argument("--confirm-lab-id")
    args = parser.parse_args(argv)
    logging.getLogger("azure").setLevel(logging.WARNING)
    output = state_path(ROOT, "demo")
    output.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC).isoformat()
    try:
        if args.command == "cleanup":
            cleanup_args = ["--setup-file", str(args.setup_file), "--lab-config", str(args.lab_config)]
            if args.apply:
                cleanup_args.append("--apply")
            if args.confirm_lab_id:
                cleanup_args.extend(["--confirm-lab-id", args.confirm_lab_id])
            return cleanup_main(cleanup_args)
        setup = json.loads(args.setup_file.read_text(encoding="utf-8-sig"))
        options = load_yaml(args.lab_config)
        if args.reconcile and args.command != "saas":
            raise ValueError("--reconcile은 saas 명령에서만 사용할 수 있습니다.")
        if args.revert and args.command != "defender":
            raise ValueError("--revert는 defender 명령에서만 사용할 수 있습니다.")
        if args.command == "plan":
            print(json.dumps(plan(setup, options), ensure_ascii=False, indent=2))
            return 0
        if args.command == "studio-publish":
            if not args.apply:
                raise ValueError("Studio 게시에는 승인 확인용 --apply가 필요합니다.")
            cli = AzureCLI()
            if cli.run("account", "show")["tenantId"].lower() != setup["tenant_id"]:
                raise ValueError("관리자 테넌트가 setup 파일과 다릅니다.")
            lab = json.loads((output / "lab.json").read_text(encoding="utf-8"))
            print("Copilot Studio 게시 시각 확인: " + studio.publish_from_receipt(cli, ROOT, lab["lab_id"]))
            return 0
        if args.command == "defender":
            if not args.apply:
                raise ValueError("Defender 플랜 변경에는 승인 확인용 --apply가 필요합니다.")
            cli = AzureCLI()
            if cli.run("account", "show")["tenantId"].lower() != setup["tenant_id"]:
                raise ValueError("관리자 테넌트가 setup 파일과 다릅니다.")
            if args.revert:
                defender.revert(cli, ROOT)
                print("Defender 플랜을 기록된 이전 상태로 복원했습니다.")
            else:
                record = defender.apply(cli, setup["subscription_ids"], ROOT)
                print(f"Defender AI·CloudPosture(Standard)·SensitiveDataDiscovery 확인: 구독 {len(record['subscriptions'])}개")
            return 0
        if args.command == "test":
            offline()
            return 0
        if args.command == "validate":

            return validate(AzureCLI(), setup, options, ROOT, args.prepare_providers)
        if args.command in ("deploy", "saas", "all"):
            if not args.apply:
                raise ValueError("샘플 배포에는 승인 확인용 --apply가 필요합니다.")
        if args.command in ("deploy", "all"):
            preflight_saas(options, setup, ROOT)
        if args.command == "saas":
            lab = json.loads((output / "lab.json").read_text(encoding="utf-8"))
            if lab["lab_id"] != plan(setup, options)["lab_id"] or lab.get("resources_deleted"):
                raise ValueError("SaaS 배포 대상 실습이 현재 Azure 실습과 다릅니다.")
            receipt = deploy_saas(options, setup, lab, ROOT, reconcile=args.reconcile)
            if receipt is not None:
                print("code-first SaaS 개인 범위/Studio 초안 배포와 실제 클라우드 검증 완료")
            return 0
        if args.command in ("deploy", "all"):
            validation = state_path(ROOT, "demo", "validation.json")
            if not validation.is_file() or not json.loads(validation.read_text())["passed"]:
                raise ValueError("배포 전 검증 .easm-agent/demo/validation.json passed=true가 필요합니다.")
        if args.command == "all":
            offline()
        cli = AzureCLI()
        if args.command in ("deploy", "all"):
            lab = deploy(cli, setup, options, ROOT, reuse_infrastructure=args.reuse_infrastructure)
            save(output / "lab.json", lab)
            if args.command == "all":
                deploy_saas(options, setup, lab, ROOT)
            if args.command == "deploy":
                print("샘플 배포 완료. 진단 수집은 collect 명령으로 별도 실행합니다.", flush=True)
                return 0
        else:
            lab = json.loads((output / "lab.json").read_text(encoding="utf-8"))
        if args.command in ("collect", "all"):
            load_verified_saas_receipt(options, setup, lab, ROOT)
        code = (
            collect_live(setup, lab, cli, options, args.skip_graph_roles)
            if args.command in ("collect", "all") else 0
        )
        save(output / "runthrough.json", {
            "started_at": started, "finished_at": datetime.now(UTC).isoformat(),
            "status": "partial" if code == 2 else "completed",
            "collection_exit_code": code, "temporary_certificate_cleaned": True,
            "sample_resources": "retained", "administrator_collection_fallback": False,
        })
        print("Run-through 완료: 샘플 유지, 일회성 인증서 정리, output/ 결과 확인", flush=True)
        return code
    except (RuntimeError, ValueError, KeyError, TypeError, OSError, AzureError, OpenAIError,
            subprocess.SubprocessError) as exc:
        save(output / "runthrough.json", {
            "started_at": started, "finished_at": datetime.now(UTC).isoformat(),
            "status": "failed", "error_type": type(exc).__name__,
            "sample_resources": "created resources are retained; rerun after fixing the reported phase",
        })
        message = str(exc) if type(exc) in (RuntimeError, ValueError, SaaSError) else type(exc).__name__
        print(f"Run-through 중단: {redact(message)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
