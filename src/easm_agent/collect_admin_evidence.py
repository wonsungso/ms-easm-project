from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from easm_agent.azure import EvidenceStore
from easm_agent.models import AdminEvidenceExport, Collection

ENVIRONMENTS_URL = "https://api.powerplatform.com/environmentmanagement/environments?api-version=2024-10-01"
COMMANDS = {
    "powerplatform.environments": ENVIRONMENTS_URL,
    "powerplatform.environment_roles": "Get-AdminPowerAppEnvironmentRoleAssignment",
    "powerplatform.dlp_policies": "Get-AdminDlpPolicy",
}


def read_admin_evidence(
    path: Path, tenant: str, now: datetime, store: EvidenceStore,
) -> Collection:
    raw = path.read_bytes()
    export = AdminEvidenceExport.model_validate_json(raw)
    if str(uuid.UUID(export.tenant_id)) != str(uuid.UUID(tenant)):
        raise ValueError("관리자 내보내기의 테넌트가 수집 대상과 다릅니다.")
    if export.exported_at > now + timedelta(minutes=5):
        raise ValueError("관리자 내보내기 시각이 현재 시각보다 미래입니다.")
    if not export.tenant_verified and any(read.completed for read in export.reads):
        raise ValueError("테넌트 미검증 관리자 내보내기를 성공 자료로 사용할 수 없습니다.")
    if len({read.source for read in export.reads}) != len(export.reads):
        raise ValueError("관리자 내보내기에 같은 조회 원천이 중복되었습니다.")
    for read in export.reads:
        if read.command != COMMANDS[read.source]:
            raise ValueError("허용된 공식 읽기 명령과 내보내기 원천이 다릅니다.")
        if read.observed_at > export.exported_at:
            raise ValueError("내보내기 시각보다 미래의 관측 자료입니다.")
        if read.environments and read.source != "powerplatform.environments":
            raise ValueError("환경 목록을 다른 명령 결과로 사용할 수 없습니다.")
        if read.source == "powerplatform.environments" and read.completed and read.object_count != len(read.environments):
            raise ValueError("환경 목록과 확인된 건수가 일치하지 않습니다.")
        if read.source == "powerplatform.environment_roles" and read.completed and (
            read.object_count != sum(read.role_counts.values())
        ):
            raise ValueError("환경별 역할 건수와 확인된 건수가 일치하지 않습니다.")
        if read.source == "powerplatform.dlp_policies" and read.completed and read.object_count != len(read.policies):
            raise ValueError("정책 범위 목록과 확인된 건수가 일치하지 않습니다.")
    ref = store.save("administrator-export:" + hashlib.sha256(raw).hexdigest(), {
        "source_type": export.source_type, "tenant_verified": export.tenant_verified,
        "export": export.model_dump(mode="json"), "input_sha256": hashlib.sha256(raw).hexdigest(),
        "verification_limit": "승인된 별도 관리자 내보내기. 진단 SP의 직접 API 조회가 아니며 파일 해시는 원천 인증 서명이 아님",
    })
    for read in export.reads:
        read.evidence_refs = [ref]
    return Collection(collected_at=now, admin_evidence=export.reads)
