"""승인된 기존 프로젝트에 플랫폼 API 샘플을 추가한다."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import AzureCliCredential
from pydantic import BaseModel, ConfigDict

from demo.agents import agent_revision, agent_tools, endpoint, evaluate_agent, sample_response
from demo.manage import ROOT, collect_live, save
from demo.saas import json_object, require, run_cli
from demo.studio import environment_url, publish_draft
from easm_agent.azure import PP_SCOPE, DelegatedReaderCredential, ReaderHTTP
from easm_agent.models import load_yaml
from easm_agent.paths import state_path
from easm_agent.report import load_result
from scripts.export_copilot_inventory import inventory_pages
from scripts.setup_account import AzureCLI

STUDIO_SAMPLES = (
    {
        "id": "minimal", "name": "EASM Studio Minimal", "description": "Synthetic sample.",
        "type": "CLI",
        "prompt": "Use synthetic governance examples only. Admit unknown facts. Never request credentials or customer data.",
    },
    {
        "id": "structured", "name": "EASM Studio Structured",
        "description": "Synthetic governance guidance with structured answers.",
        "type": "CLI",
        "prompt": "Use synthetic governance examples only. Answer in Korean with three sections: 확인한 구성, 미확인 사항, 다음 확인 단계. Never invent API evidence or request credentials.",
    },
    {
        "id": "classic", "name": "EASM Studio Classic",
        "description": "Synthetic classic authoring sample for platform configuration comparison.",
        "type": "Classic",
        "prompt": "Use synthetic Korean governance examples only. Explain that missing API data is not zero and creation is not operational deployment. Never change resources.",
    },
)


class SampleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    project_id: str
    project_endpoint: str
    model_deployment: str
    studio_environment_id: str
    msagent_executable: Path


def configuration(path: Path, root: Path, cli: AzureCLI) -> SampleConfig:
    setup = json.loads(state_path(root, "setup.json").read_text(encoding="utf-8-sig"))
    require(cli.run("account", "show")["tenantId"].casefold() == setup["tenant_id"].casefold(),
            "administrator", "승인된 관리자 테넌트 불일치")
    if path.is_file():
        config = SampleConfig.model_validate_json(path.read_text(encoding="utf-8"))
    else:
        data = load_result(root / "output")["collection"]
        projects = data["facts"]["foundry_project_endpoints"]
        environments = {row["environment_id"] for row in data["copilot_agents"]
                        if row["platform"] == "copilot_studio"}
        executables = list((root / ".easm-agent" / "tools" / "m365-automation" / "msagent").rglob(
            "Microsoft.Agents.Hosting.Cli.exe",
        ))
        require(len(projects) == len(environments) == len(executables) == 1,
                "configuration", "기존 Foundry 프로젝트·Studio 환경·CLI를 각각 하나로 지정하세요.")
        options = load_yaml(root / "demo" / "config.yaml")
        config = SampleConfig(
            tenant_id=setup["tenant_id"], project_id=projects[0]["project_id"],
            project_endpoint=projects[0]["endpoint"], model_deployment=options["deployment_name"],
            studio_environment_id=next(iter(environments)), msagent_executable=executables[0],
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    require(config.tenant_id.casefold() == setup["tenant_id"].casefold(),
            "configuration", "샘플 설정과 승인 테넌트 불일치")
    require(config.project_id.split("/")[2].casefold() in {
        sid.casefold() for sid in setup["subscription_ids"]
    }, "configuration", "승인 구독 밖 Foundry 프로젝트")
    require(config.msagent_executable.is_file(), "tools", "설치된 msagent 실행 파일이 필요합니다.")
    return config


def studio_command(root: Path, config: SampleConfig, phase: str, *args: str) -> dict[str, Any]:
    result = json_object(run_cli(root, phase, [
        str(config.msagent_executable), *args, "--json", "--non-interactive",
    ], 600), phase)
    require(result.get("success") is True and result.get("schemaVersion") == 1,
            phase, "공식 CLI success/schemaVersion 확인 실패")
    return result


def preflight(config: SampleConfig, root: Path, cli: AzureCLI) -> tuple[str, str]:
    auth = studio_command(root, config, "studio_auth", "auth", "status")
    require(auth.get("signedIn") is True and auth.get("tenantId", "").casefold() == config.tenant_id.casefold(),
            "studio_auth", "동일 테넌트의 기존 msagent 로그인이 필요합니다.")
    environments = studio_command(root, config, "studio_environment", "env", "list")
    matches = [row for row in environments["environments"]
               if row["environmentId"].casefold() == config.studio_environment_id.casefold()
               and row["tenantId"].casefold() == config.tenant_id.casefold()]
    require(len(matches) == 1, "studio_environment", "승인된 Studio 환경 접근 확인 실패")
    project = cli.run("rest", "--method", "GET", "--url",
                      "https://management.azure.com" + config.project_id + "?api-version=2025-06-01")
    require(config.project_endpoint in project["properties"]["endpoints"].values(),
            "foundry_project", "실제 Foundry 프로젝트 endpoint 불일치")
    account_id = config.project_id.rsplit("/projects/", 1)[0]
    account = cli.run("rest", "--method", "GET", "--url",
                      "https://management.azure.com" + account_id + "?api-version=2025-06-01")
    lab_id = account.get("tags", {}).get("easmagent-lab")
    require(isinstance(lab_id, str) and bool(lab_id), "foundry_project", "데모 소유 태그 미확인")
    models = cli.run("rest", "--method", "GET", "--url",
                     "https://management.azure.com" + account_id + "/deployments?api-version=2024-10-01")["value"]
    catalog = json.loads((root / "demo" / "catalog.json").read_text(encoding="utf-8"))
    required_models = {entry.get("model_deployment", config.model_deployment)
                       for entry in catalog if entry["id"].startswith("easm-demo-")}
    require(required_models <= {row["name"] for row in models},
            "foundry_models", "샘플이 참조하는 기존 모델 배포가 없습니다.")
    return lab_id, environment_url(cli, config.studio_environment_id)


def foundry_samples(config: SampleConfig, root: Path, lab_id: str, directory: Path) -> list[dict[str, Any]]:
    catalog = json.loads((root / "demo" / "catalog.json").read_text(encoding="utf-8"))
    entries = [entry for entry in catalog if entry["platform"] == "foundry" and entry["id"].startswith("easm-demo-")]
    require(len(entries) == 3, "foundry_samples", "추가 Foundry 샘플 정의는 3개여야 합니다.")
    results = []
    with AzureCliCredential(tenant_id=config.tenant_id) as credential, AIProjectClient(
        endpoint=config.project_endpoint, credential=credential, allow_preview=True,
    ) as project:
        for entry in entries:
            receipt_path = directory / (entry["id"] + ".json")
            previous = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.is_file() else None
            try:
                versions = list(project.agents.list_versions(agent_name=entry["id"]))
            except ResourceNotFoundError:
                versions = []
            require(not versions or all((row.metadata or {}).get("easmagent-lab") == lab_id for row in versions),
                    "foundry_owner", "동명 Agent의 데모 소유 태그 불일치")
            revision = agent_revision(entry)
            version = next((row for row in versions if (row.metadata or {}).get("sample_revision") == revision), None)
            if version is None:
                version = project.agents.create_version(
                    agent_name=entry["id"],
                    definition=PromptAgentDefinition(
                        model=entry.get("model_deployment", config.model_deployment),
                        instructions=entry["instructions"], tools=agent_tools(entry),
                    ),
                    description=entry.get("description"),
                    metadata={"easmagent-lab": lab_id, "sample_revision": revision, "sample_only": "true"},
                )
            project.agents.update_details(agent_name=entry["id"], agent_endpoint=endpoint(version.version))
            result = {
                "agent_id": project.agents.get(agent_name=entry["id"]).id,
                "agent_version": version.version, "model": version.definition.model,
                "description_present": bool(version.description),
                "approval": (entry.get("agent_tool") or {}).get("require_approval"),
                "revision": revision, "evaluation": None, "smoke_status": "skipped_tool_agent",
            }
            if previous and previous.get("agent_version") == version.version:
                result["evaluation"] = previous.get("evaluation")
                result["smoke_status"] = previous.get("smoke_status")
            if entry["evaluate"] and result["evaluation"] is None:
                result["evaluation"] = evaluate_agent(project, entry, version.version, directory)
            if not entry.get("agent_tool") and result["smoke_status"] == "skipped_tool_agent":
                with project.get_openai_client(agent_name=entry["id"]).with_options(
                    timeout=90, max_retries=1,
                ) as client:
                    response = sample_response(client, input="합성 예시로 역할을 한 문장으로 설명하세요.",
                                               max_output_tokens=64, store=False)
                    require(response.status == "completed" and bool(response.output_text),
                            "foundry_smoke", "Foundry 합성 응답 완료 미확인")
                result["smoke_status"] = "completed"
            save(receipt_path, result)
            results.append(result)
            print("Foundry API 샘플 확인:", entry["id"], flush=True)
        names = {row.name for row in project.agents.list()}
        require({entry["id"] for entry in entries} <= names, "foundry_verify", "새 Foundry Agent 목록 미확인")
    return results


def studio_samples(config: SampleConfig, root: Path, lab_id: str, url: str, directory: Path,
                   cli: AzureCLI) -> list[dict[str, Any]]:
    results = []
    for spec in STUDIO_SAMPLES:
        project = directory / ("studio-" + spec["id"])
        receipt = directory / ("studio-" + spec["id"] + ".json")
        schema = "easm_sample_" + spec["id"] + "_" + lab_id
        if receipt.is_file():
            record = json.loads(receipt.read_text(encoding="utf-8"))
            require(record["environment_id"] == config.studio_environment_id and record["schema_name"] == schema,
                    "studio_resume", "기존 샘플 영수증의 환경·스키마 불일치")
        else:
            require(not project.exists(), "studio_resume", "영수증 없는 작업 사본을 재생성하지 않습니다.")
            created = studio_command(
                root, config, "studio_create", "agent", "create", "--agent-type", "MCSAgent",
                "--mcs-agent-type", spec["type"], "--agent-name", spec["name"], "--schema-name", schema,
                "--description", spec["description"], "--initial-prompt", spec["prompt"],
                "--environment-id", config.studio_environment_id, "--project", str(project),
            )
            require(created["tenantId"].casefold() == config.tenant_id.casefold()
                    and created["environmentId"].casefold() == config.studio_environment_id.casefold(),
                    "studio_create", "CLI 샘플 생성 테넌트·환경 불일치")
            record = {"local_agent_id": str(UUID(created["agentId"])), "environment_id": config.studio_environment_id,
                      "schema_name": schema, "name": spec["name"], "type": spec["type"]}
            save(receipt, record)
        if "deployment_id" not in record:
            target = studio_command(
                root, config, "studio_target", "deployment", "create", "--project", str(project),
                "--agent-id", record["local_agent_id"], "--deployment-name", "demo",
                "--deployment-type", "dev", "--environment-id", config.studio_environment_id,
            )
            record["deployment_id"] = str(UUID(target["deploymentId"]))
            save(receipt, record)
        deployed = studio_command(
            root, config, "studio_deploy", "agent", "deploy", "--project", str(project),
            "--agent-id", record["local_agent_id"], "--deployment-id", record["deployment_id"],
        )
        pushed = deployed.get("pushedComponentCount")
        require(type(pushed) is int and pushed >= 0, "studio_deploy", "CLI 구성 업로드 수 미확인")
        record["agent_id"] = str(UUID(deployed["targetMcsAgentId"]))
        save(receipt, record)
        record["published_at"] = publish_draft(
            cli, url, record["agent_id"], force=pushed > 0,
        )
        bot = cli.run("rest", "--method", "GET", "--resource", url, "--url",
                      url + f"/api/data/v9.2/bots({record['agent_id']})?$select=botid,name,schemaname,publishedon")
        require(bot["name"] == spec["name"] and bot["schemaname"] == schema and bool(bot["publishedon"]),
                "studio_verify", "Studio ID·이름·스키마·게시 시각 미확인")
        save(receipt, record)
        results.append(record)
        print("Studio API 샘플 게시 확인:", spec["name"], flush=True)
    return results


def wait_for_studio_inventory(config: SampleConfig, expected: set[str], timeout_seconds: int = 1200) -> None:
    deadline = time.monotonic() + timeout_seconds
    with AzureCliCredential(tenant_id=config.tenant_id) as credential:
        http = ReaderHTTP(DelegatedReaderCredential(credential, config.tenant_id, PP_SCOPE))
        try:
            while True:
                observed = {row.agent_id for row in inventory_pages(http)
                            if row.environment_id.casefold() == config.studio_environment_id.casefold()}
                missing = expected - observed
                if not missing:
                    return
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Studio 인벤토리 반영 지연: 새 Agent {len(missing)}개 미확인")
                print(f"공식 Studio 인벤토리 반영 대기: {len(missing)}개", flush=True)
                time.sleep(30)
        finally:
            http.close()


def collect_results(config: SampleConfig, root: Path, cli: AzureCLI,
                    samples: dict[str, list[dict[str, Any]]]) -> int:
    setup = json.loads(state_path(root, "setup.json").read_text(encoding="utf-8-sig"))
    wait_for_studio_inventory(config, {row["agent_id"] for row in samples["copilot_studio"]})
    account_id = config.project_id.rsplit("/projects/", 1)[0]
    deployment = cli.run("rest", "--method", "GET", "--url",
                         "https://management.azure.com" + account_id + "/deployments/"
                         + config.model_deployment + "?api-version=2024-10-01")
    model = deployment["properties"]["model"]
    account = cli.run("rest", "--method", "GET", "--url",
                      "https://management.azure.com" + account_id + "?api-version=2025-06-01")
    lab_id = account["tags"]["easmagent-lab"]
    lab = {
        "project_id": config.project_id, "project_endpoint": config.project_endpoint,
        "model": model["name"], "model_version": model["version"],
        "chatbot_agents": samples["foundry"],
    }
    options = {
        "agent365_registry": True, "collect_all_subscriptions": True,
        "auto_grant_needed_read_roles": False, "saas": {},
        "copilot_evaluation_cli": str(config.msagent_executable),
        "copilot_evaluation_project": str(state_path(root, "demo", "samples", lab_id, "studio-classic")),
    }
    status = collect_live(setup, lab, cli, options, skip_graph_roles=True, persist_lab=False)
    data = load_result(root / "output")["collection"]
    observed_foundry = {row["agent_id"] for row in data["agents"] if row["platform"] == "foundry"}
    observed_studio = {row["agent_id"] for row in data["copilot_agents"] if row["platform"] == "copilot_studio"}
    missing_foundry = {row["agent_id"] for row in samples["foundry"]} - observed_foundry
    missing_studio = {row["agent_id"] for row in samples["copilot_studio"]} - observed_studio
    if missing_foundry or missing_studio:
        raise RuntimeError(
            f"새 샘플 수집 반영 미확인: Foundry {len(missing_foundry)}개, Studio {len(missing_studio)}개. "
            "플랫폼 인벤토리 반영 후 같은 명령을 다시 실행하세요."
        )
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=state_path(ROOT, "demo", "samples-config.json"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--collect", action="store_true", help="배포 후 별도 관리자 읽기·진단 SP로 새 보고서 수집")
    args = parser.parse_args()
    if not args.apply:
        parser.error("승인된 샘플 생성·게시에는 --apply가 필요합니다.")
    cli = AzureCLI()
    config = configuration(args.config, ROOT, cli)
    lab_id, url = preflight(config, ROOT, cli)
    directory = state_path(ROOT, "demo", "samples", lab_id)
    directory.mkdir(parents=True, exist_ok=True)
    result = {"foundry": foundry_samples(config, ROOT, lab_id, directory)}
    result["copilot_studio"] = studio_samples(config, ROOT, lab_id, url, directory, cli)
    save(directory / "receipt.json", result)
    print("API 샘플 추가 완료: Foundry 3개·Copilot Studio 3개. 기존 Agent Builder 유지.")
    return collect_results(config, ROOT, cli, result) if args.collect else 0


if __name__ == "__main__":
    raise SystemExit(main())
