"""SaaS 에이전트의 수동 생성 안내와 실제 관리자 인벤토리 검증."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from easm_agent.collect_copilot import classify_created_in, load_copilot_export


def verify(
    inventory_file: Path, tenant_id: str, agent_builder_id: str, copilot_studio_id: str,
    *, agent_builder_environment_id: str | None = None,
    copilot_studio_environment_id: str | None = None, require_published: bool = False,
) -> dict:
    export = load_copilot_export(inventory_file, tenant_id, datetime.now(UTC))
    checks = []
    for platform, identifier, environment in (
        ("agent_builder", agent_builder_id, agent_builder_environment_id),
        ("copilot_studio", copilot_studio_id, copilot_studio_environment_id),
    ):
        identifier = str(uuid.UUID(identifier))
        matches = [
            row for row in export.agents if row.agent_id == identifier
            and classify_created_in(row.created_in) == platform
            and (environment is None or row.environment_id.lower() == environment.lower())
        ]
        ready = (
            export.completed and len(matches) == 1
            and (not require_published or matches[0].last_published_at is not None)
        )
        checks.append({
            "platform": platform, "agent_id": identifier,
            "status": "verified" if ready else "not_ready",
            "matched_count": len(matches),
            "published_observed": matches[0].last_published_at is not None if len(matches) == 1 else None,
        })
    return {
        "status": "verified" if all(row["status"] == "verified" for row in checks) else "not_ready",
        "export_complete": export.completed, "reason": export.reason, "checks": checks,
        "limit": "실제 인벤토리 구성 관측만 확인 - 사용 이력 - 승인 - 라이선스 - 배포 영수증 아님",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan")
    check = commands.add_parser("verify")
    check.add_argument("--inventory-file", type=Path, required=True)
    check.add_argument("--tenant-id", required=True)
    check.add_argument("--agent-builder-id", required=True)
    check.add_argument("--copilot-studio-id", required=True)
    check.add_argument("--agent-builder-environment-id")
    check.add_argument("--copilot-studio-environment-id")
    check.add_argument("--require-published", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "plan":
        print(
            "Microsoft 365 Copilot Agent Builder와 Copilot Studio는 SaaS입니다.\n"
            "라이선스와 환경 접근 권한을 가진 사용자/관리자가 각 공식 UI에서 직접 생성합니다.\n"
            "Azure Bicep이나 미확인 생성 API로 만들지 않습니다. 게시가 필요하면 UI에서 게시합니다.\n"
            "별도 Global Reader 또는 AI Reader 사용자가 기존 Azure CLI 로그인으로 승인된 "
            "scripts\\export_copilot_inventory.py 내보내기를 수행합니다.\n"
            "약 20분 갱신 지연 후 실제 두 에이전트 ID로 verify를 실행합니다. "
            "진단 SP에 관리자 역할을 부여하지 않습니다."
        )
        return 0
    try:
        values = vars(args).copy()
        values.pop("command")
        result = verify(**values)
    except (ValueError, OSError):
        print(json.dumps({"status": "not_ready", "reason": "invalid_inventory_or_identifiers"}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
