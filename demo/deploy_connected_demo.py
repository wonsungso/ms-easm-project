"""Provision synthetic demos with named SDK profiles, separately from EASM collection."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
REGIONS = {"ap-northeast-2": "EasmSeoulSample", "ap-northeast-1": "EasmTokyoSample"}
MODELS = {"ap-northeast-2": "apac.amazon.nova-lite-v1:0", "ap-northeast-1": "amazon.nova-lite-v1:0"}
TERMINAL_FAILURES = {"CREATE_FAILED", "UPDATE_FAILED", "DELETING", "DELETE_FAILED"}


def harness_request(region: str, role: str, model: str) -> dict[str, Any]:
    request = json.loads((ROOT / "agentcore-harness.json").read_text(encoding="utf-8"))
    request.update(harnessName=REGIONS[region], executionRoleArn=role)
    request["model"]["bedrockModelConfig"]["modelId"] = model
    request["clientToken"] = hashlib.sha256(
        json.dumps([region, request], sort_keys=True).encode()
    ).hexdigest()
    return request


def matching_harness(client: Any, name: str) -> dict[str, Any] | None:
    token = None
    seen: set[str] = set()
    match = None
    while True:
        page = client.list_harnesses(**({"nextToken": token} if token else {}))
        for row in page["harnesses"]:
            if row["harnessName"] == name:
                if match is not None:
                    raise ValueError(f"같은 이름의 Harness가 여러 개입니다: {name}")
                match = row
        token = page.get("nextToken")
        if not token:
            return match
        if token in seen:
            raise ValueError("AWS Harness 목록 페이지 토큰이 반복되었습니다.")
        seen.add(token)


def verify_role(identity: dict[str, str], account: str, role: str) -> None:
    if identity["Account"] != account or identity["Arn"].endswith(":root"):
        raise ValueError("지정한 테스트 AWS 계정의 비루트 배포 프로필이 필요합니다.")
    if not re.fullmatch(rf"arn:aws:iam::{re.escape(account)}:role/[\w+=,.@/-]+", role, re.ASCII):
        raise ValueError("실행 역할은 지정한 테스트 AWS 계정에 속해야 합니다.")


def wait_ready(client: Any, harness_id: str, region: str) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        row = client.get_harness(harnessId=harness_id)["harness"]
        state = row["status"]
        if state == "READY":
            return
        if state in TERMINAL_FAILURES:
            raise ValueError(f"{region}: Harness 상태 {state}. 콘솔에서 실패 원인을 확인하세요.")
        time.sleep(5)
    raise ValueError(f"{region}: READY 확인 시간 초과. 다시 생성하기 전에 기존 상태를 확인하세요.")


def deploy_aws(args: argparse.Namespace) -> None:
    import boto3
    from botocore.config import Config

    session = boto3.Session(profile_name=args.profile)
    config = Config(ignore_configured_endpoint_urls=True, connect_timeout=5, read_timeout=15)
    identity = session.client("sts", region_name=args.region, config=config).get_caller_identity()
    verify_role(identity, args.account, args.execution_role)
    client = session.client("bedrock-agentcore-control", region_name=args.region, config=config)
    model = session.client("bedrock", region_name=args.region, config=config)
    model_id = MODELS[args.region]
    if model_id.startswith("apac."):
        model.get_inference_profile(inferenceProfileIdentifier=model_id)
    else:
        model.get_foundation_model(modelIdentifier=model_id)

    request = harness_request(args.region, args.execution_role, model_id)
    name = request["harnessName"]
    existing = matching_harness(client, name)
    print(f"{args.region}: {name}; 모델 {model_id}; 기존 상태 {existing['status'] if existing else '없음'}")
    if not args.apply:
        return
    if existing:
        raise ValueError("같은 이름의 Harness가 이미 있습니다. 덮어쓰지 않습니다.")
    created = client.create_harness(**request)["harness"]
    wait_ready(client, created["harnessId"], args.region)
    print(f"{args.region}: {name} READY. 모델 호출 없음.")


def deploy_classic(args: argparse.Namespace) -> None:
    import boto3
    from botocore.config import Config

    session = boto3.Session(profile_name=args.profile)
    config = Config(ignore_configured_endpoint_urls=True, connect_timeout=5, read_timeout=15)
    identity = session.client("sts", region_name=args.region, config=config).get_caller_identity()
    verify_role(identity, args.account, args.execution_role)
    client = session.client("bedrock-agent", region_name=args.region, config=config)
    model_id = MODELS[args.region]
    name = REGIONS[args.region].replace("Sample", "ClassicSample")
    for page in client.get_paginator("list_agents").paginate():
        if any(row["agentName"] == name for row in page["agentSummaries"]):
            raise ValueError("같은 이름의 Classic Agent가 이미 있습니다. 덮어쓰지 않습니다.")
    print(f"{args.region}: {name}; 모델 {model_id}")
    if not args.apply:
        return
    request = {
        "agentName": name, "agentResourceRoleArn": args.execution_role,
        "foundationModel": model_id,
        "instruction": "Answer short synthetic demo questions only. Do not request personal data or credentials.",
        "idleSessionTTLInSeconds": 60, "tags": {"project": "easm-connected-demo"},
    }
    request["clientToken"] = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    agent_id = client.create_agent(**request)["agent"]["agentId"]
    for expected in ("NOT_PREPARED", "PREPARED"):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = client.get_agent(agentId=agent_id)["agent"]["agentStatus"]
            if state == expected:
                break
            if state in ("FAILED", "DELETING"):
                raise ValueError(f"Classic Agent 상태 {state}. 원본 실패 사유를 확인하세요.")
            time.sleep(5)
        else:
            raise ValueError("Classic Agent 상태 확인 시간 초과. 다시 생성하지 말고 기존 상태를 확인하세요.")
        if expected == "NOT_PREPARED":
            client.prepare_agent(agentId=agent_id)
    print(f"{args.region}: {name} PREPARED. 모델 호출 없음.")


def deploy_snowflake(args: argparse.Namespace) -> None:
    import snowflake.connector

    sql = (ROOT / "cortex-agent.sql").read_text(encoding="utf-8")
    with snowflake.connector.connect(
        connection_name=args.connection, login_timeout=60, network_timeout=60,
    ) as conn, conn.cursor() as cursor:
        account, region = cursor.execute(
            "SELECT CURRENT_ORGANIZATION_NAME() || '-' || CURRENT_ACCOUNT_NAME(), CURRENT_REGION()"
        ).fetchone()
        if account.casefold() != args.account.casefold():
            raise ValueError("지정한 Snowflake 테스트 계정과 연결 프로필이 다릅니다.")
        print(f"Snowflake 리전: {region}")
        if not args.apply:
            return
        for step in conn.execute_string(sql, remove_comments=True):
            try:
                if step.description and any(col.name.lower() == "name" for col in step.description):
                    names = [col.name.lower() for col in step.description]
                    if any(row[names.index("name")] == "EASM_CORTEX_SAMPLE" for row in step.fetchall()):
                        from demo.snowflake_reader import ensure_reader, reader_key

                        ensure_reader(conn, reader_key(args.key_directory))
                        print("Snowflake: EASM_CORTEX_SAMPLE 확인. 모델 호출 없음.")
                        return
            finally:
                step.close()
        raise ValueError("Snowflake SHOW AGENTS에서 샘플을 확인하지 못했습니다.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    services = parser.add_subparsers(dest="service", required=True)
    aws = services.add_parser("aws")
    aws.add_argument("--profile", required=True)
    aws.add_argument("--account", required=True)
    aws.add_argument("--region", choices=REGIONS, required=True)
    aws.add_argument("--execution-role", required=True)
    classic = services.add_parser("aws-classic")
    classic.add_argument("--profile", required=True)
    classic.add_argument("--account", required=True)
    classic.add_argument("--region", choices=REGIONS, required=True)
    classic.add_argument("--execution-role", required=True)
    snowflake = services.add_parser("snowflake")
    snowflake.add_argument("--connection", required=True)
    snowflake.add_argument("--account", required=True)
    snowflake.add_argument("--key-directory", type=Path, required=True,
                           help="저장소 밖의 지속 RSA 폴더. 기존 키 재사용, 최초 실행 시 자동 생성")
    for service in (aws, classic, snowflake):
        service.add_argument("--apply", action="store_true", help="실제 생성. 생략하면 연결·범위 확인만 수행")
    args = parser.parse_args()
    try:
        {"aws": deploy_aws, "aws-classic": deploy_classic, "snowflake": deploy_snowflake}[args.service](args)
    except ImportError:
        print('데모 SDK 필요: python -m pip install -e ".[connected-demo]"', file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
