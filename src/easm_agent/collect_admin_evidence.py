from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from easm_agent.azure import BAP_DLP_URL, EvidenceStore
from easm_agent.models import AdminEvidenceExport, AdminReadResult, Collection

ENVIRONMENTS_URL = "https://api.powerplatform.com/environmentmanagement/environments?api-version=2024-10-01"
DATAVERSE_ROLES_COMMAND = "Dataverse Web API: systemusers + systemuserroles_association (System Administrator or Environment Maker, interactive users only)"
COMMANDS = {
    "powerplatform.environments": ENVIRONMENTS_URL,
    "powerplatform.environment_roles": "Get-AdminPowerAppEnvironmentRoleAssignment",
    "powerplatform.dataverse_roles": DATAVERSE_ROLES_COMMAND,
    "powerplatform.dlp_policies": "Get-AdminDlpPolicy",
}
PORTAL_ORIGIN = "https://admin.powerplatform.microsoft.com"
PORTAL_COMMANDS = {
    "powerplatform.environment_roles": PORTAL_ORIGIN + "/manage/environments",
    "powerplatform.dlp_policies": PORTAL_ORIGIN + "/security/dataprotection/dlp",
}


def validate_portal_read(read: AdminReadResult) -> None:
    if read.command != PORTAL_COMMANDS.get(read.source):
        raise ValueError("허용된 관리 센터 화면과 내보내기 원천이 다릅니다.")
    if not read.completed:
        if read.portal_pages:
            raise ValueError("미완료 화면 조회를 확인된 목록으로 사용할 수 없습니다.")
        return
    if not read.portal_pages or any(page.observed_at > read.observed_at for page in read.portal_pages):
        raise ValueError("완료된 관리 센터 조회에는 조회 시각 이전의 화면 증적이 필요합니다.")
    urls = [page.url for page in read.portal_pages]
    if len(set(urls)) != len(urls):
        raise ValueError("같은 관리 센터 화면이 중복되었습니다.")
    if read.source == "powerplatform.dlp_policies":
        if urls != [read.command] or read.portal_pages[0].object_count != read.object_count:
            raise ValueError("DLP 정책 화면의 목록 건수와 내보내기가 일치하지 않습니다.")
        return
    expected = {
        f"{PORTAL_ORIGIN}/manage/environments/environment/{quote(key, safe='')}/roles/{role}": key
        for key in read.role_counts
        for role in ("environmentadmin", "environmentmaker")
    }
    if set(urls) != set(expected) or len({key.lower() for key in read.role_counts}) != len(read.role_counts):
        raise ValueError("각 환경의 환경 관리자·환경 제작자 화면을 모두 확인해야 합니다.")
    counts = dict.fromkeys(read.role_counts, 0)
    for page in read.portal_pages:
        counts[expected[page.url]] += page.object_count
    if counts != read.role_counts:
        raise ValueError("관리 센터의 실제 역할 할당 건수와 내보내기가 일치하지 않습니다.")


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
        if export.source_type == "official_admin_portal_read":
            validate_portal_read(read)
        else:
            allowed = (COMMANDS[read.source],) + (
                (BAP_DLP_URL,) if read.source == "powerplatform.dlp_policies" else ()
            )
            if read.command not in allowed or read.portal_pages:
                raise ValueError("허용된 공식 읽기 명령과 내보내기 원천이 다릅니다.")
        if read.observed_at > export.exported_at:
            raise ValueError("내보내기 시각보다 미래의 관측 자료입니다.")
        if read.environments and read.source != "powerplatform.environments":
            raise ValueError("환경 목록을 다른 명령 결과로 사용할 수 없습니다.")
        if read.source == "powerplatform.environments" and read.completed and read.object_count != len(read.environments):
            raise ValueError("환경 목록과 확인된 건수가 일치하지 않습니다.")
        if read.source in ("powerplatform.environment_roles", "powerplatform.dataverse_roles") and read.completed and (
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

