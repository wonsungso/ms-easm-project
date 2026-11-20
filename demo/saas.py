"""관리자 전용 code-first SaaS 준비 - 로그인, 환경 생성, 라이선스 변경 없음."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from demo.auth import restrict_directory
from easm_agent.paths import state_path
from scripts.setup_account import cli_prefix

TOOLKIT_VERSION = "1.1.19"
MSAGENT_VERSION = "0.2.128-beta"
PP_API = "https://api.powerplatform.com"
PP_ENVIRONMENTS = PP_API + "/environmentmanagement/environments?api-version=2024-10-01"
STUDIO_NAME = "EASM Demo Studio"
DESCRIPTION = "EASM synthetic governance demonstration. No business data or external tools."
PROMPT = (
    "Use only synthetic EASM governance examples. Never request identifiers, credentials, "
    "personal or business data. Explain that configuration is not proof of policy effectiveness. "
    "Do not access knowledge, websites, connectors, tools or external systems."
)


class SaaSError(RuntimeError):
    def __init__(self, phase: str, reason: str) -> None:
        self.phase = phase
        super().__init__(f"SaaS {phase}: {reason}")


class Publisher(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=32)
    website: str
    privacy: str
    terms: str
    studio_prefix: str = Field(pattern=r"^[a-z][a-z0-9]{1,7}$")

    @field_validator("name")
    @classmethod
    def real_name(cls, value: str) -> str:
        if not value.strip() or value.lower() in ("my app, inc.", "my app inc"):
            raise ValueError("게시자 입력 필요")
        return value

    @field_validator("website", "privacy", "terms")
    @classmethod
    def real_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.port not in (None, 443)
            or parsed.hostname in ("example.com", "www.example.com", "localhost")
            or parsed.hostname.endswith((".example", ".invalid", ".test"))
        ):
            raise ValueError("승인된 게시자 HTTPS URL 필요")
        return value


class Licenses(BaseModel):
    model_config = ConfigDict(extra="forbid")
    m365_copilot: Literal[True]
    copilot_studio: Literal[True]
    existing_capacity: Literal[True]


class SaaSSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: Literal[True]
    authoring_method: Literal["code_first"]
    tenant_id: UUID
    environment_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9-]+$")
    publisher: Publisher
    licenses_confirmed: Licenses
    msagent_executable: str = ""
    timeout_seconds: int = Field(default=600, ge=10, le=1800)


class SaaSReadiness(BaseModel):
    settings: SaaSSettings
    dataverse_url: str
    organization_id: UUID
    checked_at: str


class ComponentReceipt(BaseModel):
    authoring_method: Literal["toolkit_declarative_code_first", "msagent_copilot_studio_code_first"]
    status: Literal[
        "pending", "creating_local", "local_ready", "deploying", "deployed",
        "verifying", "deployed_verified", "failed",
    ] = "pending"
    local_agent_id: str | None = None
    cloud_ids: dict[str, str] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    failed_phase: str | None = None


class SaaSReceipt(BaseModel):
    schema_version: Literal[1] = 1
    tenant_id: UUID
    environment_id: str
    lab_id: str
    configuration_sha256: str
    status: Literal["pending", "deployed_verified", "failed"] = "pending"
    components: dict[str, ComponentReceipt] = Field(default_factory=lambda: {
        "m365_declarative": ComponentReceipt(authoring_method="toolkit_declarative_code_first"),
        "copilot_studio": ComponentReceipt(authoring_method="msagent_copilot_studio_code_first"),
    })

    @field_validator("components")
    @classmethod
    def required_components(cls, value: dict[str, ComponentReceipt]) -> dict[str, ComponentReceipt]:
        expected = {
            "m365_declarative": "toolkit_declarative_code_first",
            "copilot_studio": "msagent_copilot_studio_code_first",
        }
        if set(value) != set(expected) or any(
            value[name].authoring_method != method for name, method in expected.items()
        ):
            raise ValueError("모든 필수 SaaS 구성 요소와 정확한 작성 방식이 필요합니다.")
        return value


def settings_for(options: dict, setup: dict) -> SaaSSettings | None:
    if "saas" not in options:
        return None  # 기존 로컬 Azure 전용 설정 호환.
    try:
        settings = SaaSSettings.model_validate(options["saas"])
        tenant = UUID(setup["tenant_id"])
    except (ValidationError, ValueError, KeyError, TypeError):
        raise SaaSError(
            "configuration",
            "새 tenant/environment/publisher와 기존 라이선스 - 용량 확인이 필요합니다.",
        ) from None
    if settings.tenant_id != tenant:
        raise SaaSError("configuration", "새 SaaS 테넌트와 Azure setup 테넌트 불일치")
    return settings


class CLITools:
    def __init__(self, root: Path, settings: SaaSSettings) -> None:
        self.root, self.settings = root.resolve(), settings
        tools = self.root / ".easm-agent" / "tools" / "m365-automation"
        self.toolkit = (
            tools / "atk" / "node_modules" / "@microsoft" / "m365agentstoolkit-cli" / "cli.js"
        )
        self.node = shutil.which("node")
        if settings.msagent_executable:
            self.msagent = Path(settings.msagent_executable).resolve()
        else:
            matches = list((tools / "msagent").rglob("Microsoft.Agents.Hosting.Cli.exe"))
            if len(matches) != 1:
                raise SaaSError("tools", "msagent 네이티브 실행 파일을 하나로 지정하세요. Windows/macOS 지원.")
            self.msagent = matches[0].resolve()
        if not self.node or not self.toolkit.is_file() or not self.msagent.is_file():
            raise SaaSError("tools", "사전 설치된 공식 Toolkit과 msagent가 필요합니다.")
        if self.msagent.suffix.lower() in (".cmd", ".bat", ".ps1"):
            raise SaaSError("tools", "msagent shim 대신 네이티브 실행 파일을 지정하세요.")
        package = json.loads(self.toolkit.with_name("package.json").read_text(encoding="utf-8"))
        if package.get("version") != TOOLKIT_VERSION:
            raise SaaSError("tools", "검증된 Toolkit 1.1.19가 필요합니다.")
        self.azure = cli_prefix()

    def run(self, phase: str, command: list[str]) -> str:
        environment = os.environ.copy()
        # 비대화형 Toolkit의 암호 기반 자동 로그인 경로를 사용하지 않는다.
        for key in (
            "M365_ACCOUNT_NAME", "M365_ACCOUNT_PASSWORD", "TEAMS_APP_ID", "M365_APP_ID",
            "M365_TITLE_ID", "M365_TENANT_ID", "TEAMSFX_M365_TENANT_ID",
            "AGENT_SCOPE", "TEAMSFX_ENV", "APP_NAME_SUFFIX",
        ):
            environment.pop(key, None)
        environment.update({
            "NO_COLOR": "1", "AZURE_CORE_COLLECT_TELEMETRY": "false",
            "AZURE_CORE_ONLY_SHOW_ERRORS": "true", "AZURE_LOGGING_ENABLE_LOG_FILE": "false",
            "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
        })
        try:
            result = subprocess.run(
                command, cwd=self.root, env=environment, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=self.settings.timeout_seconds,
                check=False, shell=False,
            )
        except subprocess.TimeoutExpired:
            raise SaaSError(phase, "timeout - 부분 실행 여부를 수동 확인하세요.") from None
        except OSError:
            raise SaaSError(phase, "실행 파일 시작 실패") from None
        if result.returncode:
            raise SaaSError(phase, f"exit={result.returncode} - 원문 응답은 저장/출력하지 않습니다.")
        return result.stdout

    def atk(self, phase: str, *args: str) -> str:
        guard = self.root / "demo" / "m365" / "easm-demo-declarative" / "toolkit-no-login.cjs"
        require(guard.is_file(), phase, "자동 로그인 차단 모듈이 필요합니다.")
        return self.run(phase, [
            str(self.node), "--require", str(guard), str(self.toolkit), *args,
            "--interactive", "false", "--telemetry", "false",
        ])

    def mcs(self, phase: str, *args: str) -> dict:
        result = json_object(self.run(phase, [
            str(self.msagent), *args, "--json", "--non-interactive",
        ]), phase)
        if result.get("success") is not True or result.get("schemaVersion") != 1:
            raise SaaSError(phase, "공식 CLI success/schemaVersion 확인 실패")
        return result

    def az(self, phase: str, *args: str) -> dict:
        return json_object(self.run(phase, [
            *self.azure, *args, "--only-show-errors", "--output", "json",
        ]), phase)

    def get(self, phase: str, url: str, audience: str) -> dict:
        return self.az(phase, "rest", "--method", "GET", "--resource", audience, "--url", url)

    def toolkit_tenant(self) -> UUID:
        # Toolkit 1.1.19 cacheAccess.ts + codeFlowLogin.ts:
        # 이 비밀이 아닌 메타데이터가 silent token 요청의 authority를 결정한다.
        # 토큰/계정 캐시를 읽거나 복사하지 않는다. online accountShow.ts 출력도 필수다.
        metadata = Path.home() / ".fx" / "account" / "tenantId.cache.appStudio"
        try:
            before = UUID(metadata.read_text(encoding="utf-8").strip())
            output = self.atk("toolkit_auth", "auth", "list", "m365")
            after = UUID(metadata.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            raise SaaSError("toolkit_auth", "기존 Toolkit 테넌트 인증 메타데이터가 필요합니다.") from None
        output = re.sub(r"\x1b\[[0-9;]*m", "", output)
        # 이 tenant-qualified 형식은 online getJsonObject 성공 경로에만 있다.
        if before != after or not re.search(
            r"Your Microsoft 365 account is: [^\r\n]+\([^\r\n()]+\)\.", output,
        ) or "(undefined)" in output:
            raise SaaSError("toolkit_auth", "온라인 Toolkit 테넌트 인증을 증명하지 못했습니다.")
        return before


def json_object(text: str, phase: str) -> dict:
    try:
        value = json.loads(text)
    except ValueError:
        raise SaaSError(phase, "JSON 응답 확인 실패") from None
    if not isinstance(value, dict) or not value:
        raise SaaSError(phase, "비어 있거나 잘못된 응답")
    return value


def require(condition: bool, phase: str, reason: str) -> None:
    if not condition:
        raise SaaSError(phase, reason)


def text(mapping: dict, key: str) -> str:
    value = mapping.get(key)
    return value if isinstance(value, str) else ""


def rows(mapping: dict, key: str, phase: str) -> list[dict]:
    value = mapping.get(key)
    require(
        isinstance(value, list) and all(isinstance(row, dict) for row in value),
        phase, "공식 응답 배열 확인 실패",
    )
    return value


def preflight_saas(options: dict, setup: dict, root: Path) -> SaaSReadiness | None:
    """모든 Azure 쓰기 전에 실행하는 읽기 전용 필수 점검. 기존 인증만 사용."""
    settings = settings_for(options, setup)
    if settings is None:
        return None
    tools = CLITools(root, settings)
    tenant, environment = str(settings.tenant_id), settings.environment_id
    node_version = tools.run("node_version", [str(tools.node), "--version"])
    match = re.fullmatch(r"v(\d+)\.(\d+)\.\d+\s*", node_version)
    if match is None:
        raise SaaSError("tools", "Node 버전 확인 실패")
    major, minor = int(match[1]), int(match[2])
    require(
        (major == 20 and minor >= 19) or (major == 22 and minor >= 12) or major > 22,
        "tools", "Toolkit 지원 Node 20.19 또는 22.12 이상이 필요합니다.",
    )
    require(tools.toolkit_tenant() == settings.tenant_id, "toolkit_auth", "테넌트 불일치")
    version = tools.run("msagent_version", [str(tools.msagent), "--version"])
    require(
        bool(re.search(r"(?<![\w.-])0\.2\.128-beta(?:\+[0-9a-f]+)?(?=\s|$|\))", version)),
        "tools", "검증된 msagent 0.2.128-beta가 필요합니다.",
    )
    auth = tools.mcs("studio_auth", "auth", "status")
    require(
        auth.get("signedIn") is True and text(auth, "tenantId").lower() == tenant,
        "studio_auth", "기존 msagent 로그인과 지정 테넌트가 필요합니다. 자동 로그인하지 않습니다.",
    )
    environments = tools.mcs("studio_environment", "env", "list")
    matches = [
        row for row in rows(environments, "environments", "studio_environment")
        if text(row, "environmentId").lower() == environment.lower()
        and text(row, "tenantId").lower() == tenant
    ]
    require(len(matches) == 1, "studio_environment", "지정 테넌트/환경 접근 확인 실패")
    context = tools.az("azure_auth", "account", "show")
    require(text(context, "tenantId").lower() == tenant, "azure_auth", "테넌트 불일치")
    inventory = tools.get("dataverse_environment", PP_ENVIRONMENTS, PP_API + "/")
    require(
        not inventory.get("nextLink") and not inventory.get("@odata.nextLink")
        and not inventory.get("@odata.nextlink"),
        "dataverse_environment", "환경 목록이 불완전합니다.",
    )
    environments = [
        row for row in rows(inventory, "value", "dataverse_environment")
        if text(row, "id").lower() == environment.lower()
    ]
    require(len(environments) == 1, "dataverse_environment", "실제 Power Platform 환경 확인 실패")
    selected = environments[0]
    require(text(selected, "tenantId").lower() == tenant, "dataverse_environment", "테넌트 불일치")
    try:
        dataverse_id = UUID(text(selected, "dataverseId"))
    except ValueError:
        raise SaaSError("dataverse_environment", "연결된 Dataverse 조직 ID 확인 실패") from None
    url = text(selected, "url").rstrip("/")
    parsed = urlsplit(url)
    require(
        parsed.scheme == "https" and bool(parsed.hostname)
        and bool(re.fullmatch(r"[a-z0-9-]+\.crm[0-9]*\.dynamics\.com", parsed.hostname or ""))
        and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
        and parsed.path in ("", "/") and parsed.port in (None, 443),
        "dataverse_environment",
        "준비된 공용 클라우드 Dataverse 환경이 필요합니다. E7만으로 데이터베이스가 생성되지 않습니다.",
    )
    who = tools.get("dataverse_read", url + "/api/data/v9.2/WhoAmI", url)
    try:
        organization = UUID(who["OrganizationId"])
        UUID(who["UserId"])
    except (ValueError, KeyError, TypeError):
        raise SaaSError("dataverse_read", "Dataverse 데이터베이스/접근 확인 실패") from None
    require(organization == dataverse_id, "dataverse_read", "환경과 Dataverse 조직 ID 불일치")
    return SaaSReadiness(
        settings=settings, dataverse_url=url, organization_id=organization,
        checked_at=datetime.now(UTC).isoformat(),
    )


def source_fingerprint(root: Path, settings: SaaSSettings) -> str:
    digest = hashlib.sha256(settings.model_dump_json().encode())
    source = root / "demo" / "m365" / "easm-demo-declarative"
    for parts in (
        ("appPackage", "manifest.json"), ("appPackage", "declarativeAgent.json"),
        ("appPackage", "instruction.txt"), ("env", ".env.dev"), ("env", ".env.local"),
        ("m365agents.yml",), ("m365agents.local.yml",), ("toolkit-no-login.cjs",),
    ):
        digest.update(source.joinpath(*parts).read_bytes())
    digest.update((PROMPT + DESCRIPTION + TOOLKIT_VERSION + MSAGENT_VERSION).encode())
    return digest.hexdigest()


def studio_schema(settings: SaaSSettings, lab_id: str) -> str:
    return settings.publisher.studio_prefix + "_easm" + hashlib.sha256(lab_id.encode()).hexdigest()[:12]


def load_verified_saas_receipt(
    options: dict, setup: dict, lab: dict, root: Path,
) -> SaaSReceipt | None:
    """관리자 재인증 없이 수집 연결용으로 검증 완료 영수증만 읽는다."""
    settings = settings_for(options, setup)
    if settings is None:
        return None
    lab_id = lab["lab_id"]
    require(
        bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", lab_id)),
        "receipt", "안전한 lab_id가 필요합니다.",
    )
    path = state_path(root, "demo", "saas", lab_id, "receipt.json")
    try:
        receipt = SaaSReceipt.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SaaSError("receipt", "필수 SaaS 배포/클라우드 검증 완료 영수증이 필요합니다.") from None
    require(
        receipt.tenant_id == settings.tenant_id and receipt.environment_id == settings.environment_id
        and receipt.lab_id == lab_id
        and receipt.configuration_sha256 == source_fingerprint(root, settings)
        and receipt.status == "deployed_verified"
        and all(row.status == "deployed_verified" for row in receipt.components.values()),
        "receipt", "영수증의 대상/소스/필수 SaaS 검증 완료 상태 불일치",
    )
    return receipt


def write_receipt(path: Path, receipt: SaaSReceipt) -> None:
    staged = path.with_suffix(".new")
    staged.write_text(receipt.model_dump_json(indent=2), encoding="utf-8")
    staged.replace(path)


def env_values(project: Path) -> dict[str, str]:
    values = {}
    for line in (project / "env" / ".env.dev").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    return values


def prepare_toolkit(root: Path, project: Path, publisher: Publisher) -> None:
    source = root / "demo" / "m365" / "easm-demo-declarative"
    require(not project.exists(), "toolkit_copy", "기존 작업 사본을 자동 덮어쓰지 않습니다.")
    shutil.copytree(source, project, ignore=shutil.ignore_patterns(
        "build", "node_modules", ".env.*.user", ".*.user", ".git",
    ))
    manifest_path = project / "appPackage" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["developer"] = {
        "name": publisher.name, "websiteUrl": publisher.website,
        "privacyUrl": publisher.privacy, "termsOfUseUrl": publisher.terms,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for name in (".env.dev", ".env.local"):
        path = project / "env" / name
        text = path.read_text(encoding="utf-8")
        require("AGENT_SCOPE=personal" in text, "toolkit_scope", "개인 범위만 허용합니다.")
    for filename in ("m365agents.yml", "m365agents.local.yml"):
        lifecycle = project / filename
        text = lifecycle.read_text(encoding="utf-8")
        require("scope: personal" in text, "toolkit_scope", "개인 범위만 허용합니다.")
    require(not env_values(project).get("TEAMS_APP_ID"), "toolkit_copy", "소스에 실제 ID가 있습니다.")


def launch_body(output: str) -> dict:
    # Toolkit logger.info는 JSON 앞에 [INFO] 접두사를 붙일 수 있다.
    candidates = []
    for match in re.finditer(r"(?m)^(?:\[[^\r\n]+\]\s*[-:]?\s*)?(\{)", output):
        try:
            value, _ = json.JSONDecoder().raw_decode(output[match.start(1):])
        except ValueError:
            continue
        if isinstance(value, dict) and value:
            candidates.append(value)
    require(len(candidates) == 1, "toolkit_verify", "실제 launchinfo JSON 본문 확인 실패")
    return candidates[0]


def verify_toolkit(tools: CLITools, component: ComponentReceipt) -> None:
    ids = component.cloud_ids
    by_manifest = launch_body(tools.atk(
        "toolkit_verify", "launchinfo", "--manifest-id", ids["teams_app_id"],
    ))
    by_title = launch_body(tools.atk(
        "toolkit_verify", "launchinfo", "--title-id", ids["m365_title_id"],
    ))
    require(
        by_manifest == by_title and by_manifest.get("success") is not False
        and "error" not in by_manifest,
        "toolkit_verify", "manifest/title 클라우드 매핑 확인 실패",
    )
    component.evidence = {
        "operation": "atk launchinfo --manifest-id + --title-id",
        "matching_cloud_responses": True,
        "response_sha256": hashlib.sha256(json.dumps(
            by_manifest, sort_keys=True,
        ).encode()).hexdigest(),
        "requested_scope": "personal",
    }


def verify_studio_source(project: Path, schema: str) -> None:
    definitions = list(project.rglob("*.mcs.yml"))
    require(
        len(definitions) == 1 and definitions[0].name == "settings.mcs.yml",
        "studio_source_verify", "설정 전용 원본 이외의 Studio 구성 요소가 있습니다.",
    )
    try:
        source = yaml.safe_load(definitions[0].read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        raise SaaSError("studio_source_verify", "Studio 원본 설정을 읽지 못했습니다.") from None
    require(isinstance(source, dict), "studio_source_verify", "Studio 원본 설정 형식 오류")
    configuration = source.get("configuration")
    agent_settings = configuration.get("agentSettings") if isinstance(configuration, dict) else None
    model = agent_settings.get("model") if isinstance(agent_settings, dict) else None
    series = model.get("series") if isinstance(model, dict) else None
    expected = {
        "displayName": STUDIO_NAME,
        "schemaName": schema,
        "accessControlPolicy": "GroupMembership",
        "authenticationMode": "Integrated",
        "authenticationTrigger": "Always",
        "configuration": {
            "recognizer": {"kind": "CLICopilotRecognizer"},
            "agentSettings": {
                "model": {"series": series},
                "instructions": {"segments": [{"kind": "StaticSegment", "value": PROMPT}]},
            },
            "authoringModel": "CliCopilot",
        },
        "template": "cliagent-1.0.0",
        "language": 1033,
    }
    require(
        isinstance(series, str) and bool(series) and source == expected,
        "studio_source_verify", "Studio 합성 지침 또는 제한된 설정이 원본과 일치하지 않습니다.",
    )


def verify_studio(
    tools: CLITools, ready: SaaSReadiness, component: ComponentReceipt, project: Path,
) -> None:
    ids = component.cloud_ids
    cloud_id = str(UUID(ids["mcs_agent_id"]))
    verify_studio_source(project, ids["schema_name"])
    local = tools.mcs(
        "studio_local_binding", "agent", "show", "--project", str(project),
        "--agent-id", str(component.local_agent_id),
    )
    bindings = rows(local, "agents", "studio_local_binding")
    deployments = [
        row for row in rows(local, "deployments", "studio_local_binding")
        if row.get("deploymentId") == ids.get("local_deployment_id")
    ]
    require(
        len(bindings) == 1 and bindings[0].get("agentId") == component.local_agent_id
        and text(bindings[0], "mcsAgentId").lower() == cloud_id
        and text(bindings[0], "tenantId").lower() == str(ready.settings.tenant_id)
        and text(bindings[0], "environmentId").lower() == ready.settings.environment_id.lower()
        and bindings[0].get("mcsSchemaName") == ids["schema_name"]
        and bindings[0].get("description") == DESCRIPTION
        and len(deployments) == 1 and deployments[0].get("agentId") == component.local_agent_id
        and deployments[0].get("deploymentType") == "dev"
        and text(deployments[0], "environmentId").lower() == ready.settings.environment_id.lower(),
        "studio_local_binding", "기록된 정확한 클라우드 ID/테넌트/환경 연결 불일치",
    )
    bot = tools.get(
        "studio_cloud_verify",
        ready.dataverse_url + f"/api/data/v9.2/bots({cloud_id})?$select=botid,schemaname,name,publishedon",
        ready.dataverse_url,
    )
    require(
        text(bot, "botid").lower() == cloud_id
        and bot.get("schemaname") == ids["schema_name"] and bot.get("name") == STUDIO_NAME
        and "publishedon" in bot and bot["publishedon"] is None,
        "studio_cloud_verify", "실제 Dataverse 에이전트 ID/스키마/이름 또는 미게시 상태 확인 실패",
    )
    with tempfile.TemporaryDirectory(prefix="easm-saas-verify-") as directory:
        temporary = Path(directory)
        restrict_directory(temporary)
        copied_project = temporary / "project"
        shutil.copytree(project, copied_project)
        pulled = tools.mcs(
            "studio_content_verify", "agent", "pull", "--project", str(copied_project),
            "--agent-id", str(component.local_agent_id),
        )
    require(
        pulled.get("agentId") == component.local_agent_id
        and text(pulled, "environmentId").lower() == ready.settings.environment_id.lower()
        and pulled.get("status") == "up-to-date" and pulled.get("changeCount") == 0
        and not pulled.get("warnings"),
        "studio_content_verify", "클라우드 콘텐츠 일치 확인 실패 - 자동 덮어쓰기하지 않습니다.",
    )
    component.evidence.update({
        "operation": "Dataverse bots GET + msagent agent pull",
        "local_source_matched": True, "cloud_identity_matched": True, "cloud_content_up_to_date": True,
        "published": False,
    })


def deploy_saas(
    options: dict, setup: dict, lab: dict, root: Path, *, reconcile: bool = False,
) -> SaaSReceipt | None:
    ready = preflight_saas(options, setup, root)
    if ready is None:
        require(not reconcile, "reconcile", "SaaS 설정이 없어 복구할 수 없습니다.")
        return None
    lab_id = lab["lab_id"]
    require(
        bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", lab_id)),
        "state", "안전한 lab_id가 필요합니다.",
    )
    tools = CLITools(root, ready.settings)
    directory = state_path(root, "demo", "saas", lab_id)
    directory.mkdir(parents=True, exist_ok=True)
    restrict_directory(directory)
    receipt_file = directory / "receipt.json"
    fingerprint = source_fingerprint(root, ready.settings)
    lock = directory / "execution.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise SaaSError("state", "동시 실행/중단된 실행 잠금이 있습니다. 실제 상태를 수동 확인하세요.") from None
    active: ComponentReceipt | None = None
    try:
        handle.close()
        if receipt_file.exists():
            receipt = SaaSReceipt.model_validate_json(receipt_file.read_text(encoding="utf-8"))
            require(
                receipt.tenant_id == ready.settings.tenant_id
                and receipt.environment_id == ready.settings.environment_id
                and receipt.lab_id == lab_id and receipt.configuration_sha256 == fingerprint,
                "state", "기존 영수증의 테넌트/환경/설정/실습 불일치",
            )
        else:
            require(not reconcile, "reconcile", "복구할 SaaS 영수증이 없습니다.")
            receipt = SaaSReceipt(
                tenant_id=ready.settings.tenant_id, environment_id=ready.settings.environment_id,
                lab_id=lab_id, configuration_sha256=fingerprint,
            )
            write_receipt(receipt_file, receipt)
        if reconcile:
            toolkit = receipt.components["m365_declarative"]
            studio = receipt.components["copilot_studio"]
            summary = studio.evidence.get("deploy_response_summary", {})
            warning_count = summary.get("warning_count") if isinstance(summary, dict) else None
            require(
                receipt.status == "failed" and toolkit.status == "deployed_verified"
                and studio.status == "failed" and studio.failed_phase == "studio_deploy"
                and studio.local_agent_id is not None
                and studio.cloud_ids.get("schema_name") == studio_schema(ready.settings, lab_id)
                and bool(studio.cloud_ids.get("local_deployment_id"))
                and bool(studio.cloud_ids.get("mcs_agent_id"))
                and (warning_count is None or type(warning_count) is int and warning_count == 0),
                "reconcile", "정확한 Studio 생성 ID가 없거나 기존 경고가 있어 자동 복구할 수 없습니다.",
            )
            verify_toolkit(tools, toolkit)
            verify_studio(tools, ready, studio, directory / "copilot_studio")
            now = datetime.now(UTC).isoformat()
            toolkit.evidence["verified_at"] = now
            studio.evidence.update({
                "reconciled_after_failed_deploy": True,
                "initial_deployment_warnings": "not_recorded" if warning_count is None else "none",
                "verified_at": now,
            })
            studio.status, studio.failed_phase = "deployed_verified", None
            receipt.status = "deployed_verified"
            write_receipt(receipt_file, receipt)
            return receipt
        require(receipt.status != "failed", "state", "실패한 실행은 자동 재생성하지 않습니다. 정확한 ID로 수동 조정하세요.")
        require(
            receipt.status != "deployed_verified" or all(
                component.status == "deployed_verified" for component in receipt.components.values()
            ),
            "state", "완료 영수증의 필수 구성 요소 상태가 일치하지 않습니다.",
        )
        for name, component in receipt.components.items():
            active = component
            require(
                component.status in ("pending", "deployed", "deployed_verified"),
                "state", "부분 실행 상태 - 중복 생성을 방지하기 위해 수동 조정이 필요합니다.",
            )
            project = directory / name
            if component.status == "pending":
                require(not project.exists(), "state", "기존 작업 사본을 자동 재사용/재생성하지 않습니다.")
                component.status = "creating_local"
                write_receipt(receipt_file, receipt)
                if name == "m365_declarative":
                    prepare_toolkit(root, project, ready.settings.publisher)
                else:
                    schema = studio_schema(ready.settings, lab_id)
                    created = tools.mcs(
                        "studio_scaffold", "agent", "create", "--agent-type", "MCSAgent",
                        "--agent-name", STUDIO_NAME, "--schema-name", schema,
                        "--description", DESCRIPTION, "--initial-prompt", PROMPT,
                        "--environment-id", ready.settings.environment_id, "--project", str(project),
                    )
                    require(
                        created.get("status") == "agent-created"
                        and created.get("createdFrom") == "scaffold"
                        and text(created, "tenantId").lower() == str(ready.settings.tenant_id)
                        and created.get("environmentId") == ready.settings.environment_id
                        and created.get("schemaName") == schema and not created.get("mcsAgentId")
                        and not created.get("warnings"),
                        "studio_scaffold", "로컬 scaffold/대상 확인 실패",
                    )
                    component.local_agent_id = str(UUID(created["agentId"]))
                    component.cloud_ids["schema_name"] = schema
                    write_receipt(receipt_file, receipt)
                    target = tools.mcs(
                        "studio_target", "deployment", "create", "--project", str(project),
                        "--agent-id", component.local_agent_id, "--deployment-name", "demo",
                        "--deployment-type", "dev", "--environment-id", ready.settings.environment_id,
                    )
                    require(
                        target.get("status") == "deployment-slot-created"
                        and target.get("agentId") == component.local_agent_id
                        and target.get("targetEnvironmentId") == ready.settings.environment_id,
                        "studio_target", "로컬 배포 대상 확인 실패",
                    )
                    component.cloud_ids["local_deployment_id"] = str(UUID(target["deploymentId"]))
                component.status = "deploying"
                write_receipt(receipt_file, receipt)
                if name == "m365_declarative":
                    tools.atk("toolkit_provision", "provision", "--folder", str(project), "--env", "dev")
                    values = env_values(project)
                    component.cloud_ids = {
                        "teams_app_id": str(UUID(values["TEAMS_APP_ID"])),
                        "m365_title_id": values["M365_TITLE_ID"],
                        "m365_app_id": str(UUID(values["M365_APP_ID"])),
                    }
                    require(
                        bool(re.fullmatch(r"[A-Za-z0-9_-]{1,150}", values["M365_TITLE_ID"])),
                        "toolkit_provision", "실제 M365 title ID 확인 실패",
                    )
                else:
                    result = tools.mcs(
                        "studio_deploy", "agent", "deploy", "--project", str(project),
                        "--agent-id", str(component.local_agent_id),
                        "--deployment-id", component.cloud_ids["local_deployment_id"],
                    )
                    cloud_id = str(UUID(result["targetMcsAgentId"]))
                    component.cloud_ids["mcs_agent_id"] = cloud_id
                    pushed_count = result.get("pushedComponentCount")
                    warnings = result.get("warnings")
                    component.evidence["deploy_response_summary"] = {
                        "status_matches": result.get("status") == "deployment-submitted",
                        "pushed_component_count": pushed_count if type(pushed_count) is int else None,
                        "published": result.get("published") if type(result.get("published")) is bool else None,
                        "warning_count": len(warnings) if isinstance(warnings, list) else None,
                    }
                    write_receipt(receipt_file, receipt)
                    require(
                        result.get("status") == "deployment-submitted"
                        and result.get("agentId") == component.local_agent_id
                        and result.get("deploymentId") == component.cloud_ids["local_deployment_id"]
                        and result.get("targetEnvironmentId") == ready.settings.environment_id
                        and result.get("schemaName") == component.cloud_ids["schema_name"]
                        and type(pushed_count) is int and pushed_count >= 0
                        and not result.get("warnings") and result.get("published") is False,
                        "studio_deploy", "실제 클라우드 ID/대상/콘텐츠 배포 확인 실패",
                    )
                    component.evidence["pushed_component_count"] = pushed_count
                component.status = "deployed"
                write_receipt(receipt_file, receipt)
            component.status = "verifying"
            write_receipt(receipt_file, receipt)
            if name == "m365_declarative":
                verify_toolkit(tools, component)
            else:
                verify_studio(tools, ready, component, project)
            component.status = "deployed_verified"
            component.evidence["verified_at"] = datetime.now(UTC).isoformat()
            write_receipt(receipt_file, receipt)
        receipt.status = "deployed_verified"
        write_receipt(receipt_file, receipt)
        return receipt
    except (SaaSError, OSError, ValueError, KeyError, TypeError) as exc:
        if active is not None:
            active.status = "failed"
            active.failed_phase = exc.phase if isinstance(exc, SaaSError) else "response_or_local_state"
            receipt.status = "failed"
            write_receipt(receipt_file, receipt)
        if isinstance(exc, SaaSError):
            raise
        raise SaaSError("response_or_local_state", "응답/로컬 상태 확인 실패 - 자동 재생성하지 않습니다.") from None
    finally:
        lock.unlink()
