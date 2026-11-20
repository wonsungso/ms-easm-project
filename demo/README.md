# 개발용 데모

**고객 진단에는 필요하지 않습니다.** 고객 절차는 [README](../README.md), API·권한 근거는 [API 참고](../docs/api-notes.md)를 따릅니다. 관리자 배포와 Reader SP 수집은 분리하며 수집기는 `demo`를 import하지 않습니다.

## 배포와 실행

| 준비·범위 | 내용 |
| --- | --- |
| 실행 위치·권한 | 프로젝트 루트, 승인된 관리자, `.easm-agent/setup.json` |
| 입력 | `tenant_id`·`subscription_ids`·`account_name`, [config.yaml](config.yaml)의 새 SaaS 테넌트·환경·게시자·기존 라이선스 확인 |
| 배포 대상 | Foundry·모델·웹 앱·로그 + 개인 범위 M365 선언형 Agent·Studio 초안. [catalog.json](catalog.json): Foundry 8개·LangChain 2개 |
| 승인 조건 | Korea Central·소형 모델·합성 데이터, GlobalStandard 처리·공급자 등록 승인 |
| 진단 SP | 별도 준비. 없으면 진단 역할 생성·할당 생략 |

```bash
bash scripts/setup.sh login
bash demo/run.sh --apply
```

- 인프라·로그인 보호 챗봇 10개·실제 평가 4건을 준비·유지합니다. 진단 SP 생성·수집은 별도이며 통합 수집은 SP 준비 후 `bash demo/run.sh --apply --collect`로 실행합니다.
- 배포 전 테스트·Ruff·Bicep·구독별 ARM validate/what-if·정책 조회를 수행합니다. 삭제 계획이 있으면 중단하고 검증 증거는 `.easm-agent/demo/validation.json`에 저장합니다.
- **비용이 발생합니다.** 모델·로그 비용은 별도이며 설정의 USD 100은 승인 예산이지 과금 상한이 아닙니다.

## 개별 명령과 실패 후 재개

| 목적 | 프로젝트 루트에서 실행 |
| --- | --- |
| 계획·테스트 | `python -m demo.manage plan` / `python -m demo.manage test` |
| 사전 검증 | `python -m demo.manage validate --prepare-providers` |
| 인프라 재사용 배포 | `python -m demo.manage deploy --apply --reuse-infrastructure` |
| Agent·웹 앱 배포 | `python -m demo.agents --apply` |
| SaaS 코드 배포·검증 | `python -m demo.manage saas --apply` |
| 실패한 Studio 초안 읽기 전용 재검증 | `python -m demo.manage saas --apply --reconcile` |
| Reader 수집 | `python -m demo.manage collect` |
| Defender 플랜 적용(관리자) | `python -m demo.manage defender --apply` - 구독의 AI·CloudPosture 플랜을 Standard로, SensitiveDataDiscovery 확장을 켬. 이전 상태를 `.easm-agent/demo/defender.json`에 기록하며 `--apply --revert`로 복원. 사용량 기반 요금 발생 가능 |
| Studio 초안 게시(관리자) | `python -m demo.manage studio-publish --apply` - 영수증의 Studio 초안을 해당 환경에서만 게시. 게시 후에야 Power Platform 인벤토리에 나타나며 반영에 시간이 걸림. 이후 `saas --reconcile`의 미게시 확인은 적용되지 않음 |
| 기존 결과 검증 | `python -m demo.diagnostics verify` |
| Codespaces 검증 | `python -m demo.diagnostics codespace --codespace '<Codespace 이름>' --apply` |

- **재개:** 실패한 단계만 같은 명령으로 실행합니다. `.easm-agent/demo/`의 `lab.json`·`runthrough.json`·`chatbot-expansion/` 영수증을 확인하며, 재사용 배포도 소유 태그·검증 증거를 확인하고 없는 리소스를 임의 생성하지 않습니다.
- **Kudu 상태:** ZIP 접수 후 상태 조회의 시간 초과·일시 오류는 재전송 없이 재조회합니다. 접수 또는 완료 여부가 끝내 미확인이면 재전송 전에 실제 배포 ID·상태·실행 코드를 확인합니다.
- **인증:** `collect`는 임시 공개 인증서·저장소 밖 개인키를 사용하고 종료 시 새 인증서만 정리합니다. 강제 종료 시 잔여 여부를 확인합니다.
- **권한:** 실제 거부 확인 시에만 설정에 따라 Cost Management Reader·작업 영역 Log Analytics Reader를 추가합니다. `auto_grant_needed_read_roles: false`로 비활성화할 수 있으며 관리자 수집으로 대체하지 않습니다.
- **Agent 365:** 라이선스와 `CopilotPackages.Read.All` 관리자 동의를 확인한 뒤 `bash scripts/setup.sh plan --agent365-reader`, `apply --agent365-reader`를 실행하고 [config.yaml](config.yaml)의 `agent365_registry: true`를 설정합니다. 기본값은 비활성화입니다.
- **관리자 증적 첨부:** `admin_evidence_files`에 승인된 관리자 내보내기(환경 목록, Power Platform 명령 결과, `scripts/export_dataverse_roles.py` 결과)의 절대 경로를 지정하면 `collect`가 함께 반영합니다. 기본값은 비어 있습니다.
- **결과:** 실행별 `output/<실행시각-UTC>/`를 보존하며 [출력 형식](../README.md#step-4)은 공통입니다. 종료 코드 `2`의 자료 미확보 사유도 유지합니다.
- **검증:** `verify`는 통합 수집 결과·역할·인증서 잔여 수·HTTP 상태를 읽고 테스트하며 배포·추론·역할 변경은 하지 않습니다.

기존 실행 상태를 보존하려면 관리자 실행 전에 `EASM_AGENT_STATE_DIR`을 새 빈 절대 경로로, `EASM_AGENT_LAB_CONFIG`를 별도로 준비한 데모 설정의 절대 경로로 지정합니다. setup·검증·Agent·SaaS 영수증과 권한 점검 결과는 지정한 상태 경로를 사용하며, 설정하지 않으면 기존 경로를 사용합니다. 도구 설치는 `.easm-agent/tools/`, 최종 결과는 `output/`에 유지됩니다.

## M365 선언형 Agent·Copilot Studio 코드 데모

`demo/run.sh --apply`는 필수 SaaS 사전 점검 후 Azure·Agent·SaaS 코드 배포를 순서대로 수행합니다. 기본 설정의 테넌트·환경·게시자·라이선스 확인 값은 비어 있어 기존 환경에 우발적으로 재배포하지 않습니다. 완료 여부는 각 실행의 영수증과 검증 결과로 확인합니다.

| 구분 | 자동화·경계 |
| --- | --- |
| M365 | [공식 Toolkit scaffold](m365/easm-demo-declarative)·선언형 manifest·합성 지침. 개인 범위 `atk provision`만 실행하며 조직 카탈로그에 게시하지 않음 |
| 작성 출처 | Toolkit 코드 작성은 Agent Builder UI 작성과 다름. 수집 결과를 Agent Builder로 위장하지 않으며 API의 `createdIn`을 유지 |
| Studio | 공식 Preview `msagent`의 로컬 정의·dev 대상·초안 push와 Dataverse ID·콘텐츠·미게시 상태 검증. 로컬 등록을 클라우드 생성 성공으로 취급하지 않음 |
| 사전 점검 | 같은 테넌트의 Azure/Toolkit/Studio 인증과 Power Platform 환경·Dataverse 조직 ID·접근을 확인. 명시적 라이선스·용량 확인값이 필요하며 Azure 쓰기 전에 실패 차단 |
| 필요한 입력 | `saas.tenant_id`, `environment_id`, 게시자 이름·HTTPS website/privacy/terms·Studio 접두사, `licenses_confirmed` |
| 환경 생성 | E7만으로 Dataverse 환경이 생기지 않음. 준비된 승인 환경이 필요하며 `pac admin create` 기반 신규 환경·용량·청구 설정은 별도 승인 범위 |
| 재개 | Studio ID가 기록된 배포 응답 실패만 `--reconcile`로 대상·합성 원본·클라우드 콘텐츠·미게시 상태를 읽기 전용 재검증. 기록된 경고가 있으면 중단하며 복사본에서만 pull하고 재생성·`--overwrite`·재배포하지 않음 |
| 수집 | `--collect`는 별도 승인 사용자로 Copilot 인벤토리·CA를 최소 필드 내보내기 후 진단 SP 결과에 첨부. 거부는 null·사유 유지. Azure 비용 이력도 별도 수집 |
| 라이선스·인증 | 자동 로그인·평가판 활성화·구매·청구 연결 없음. E7 계약·사용자 할당·Studio 용량은 실제 환경에서 확인 |
| 실행 OS | SaaS CLI 검증 경로는 Windows/macOS. Linux Codespaces의 SaaS 배포 지원을 가정하지 않음 |

```powershell
# 승인된 로컬 도구 설치 - 프로젝트 전용, 인증·클라우드 배포 없음
npm install --prefix .easm-agent\tools\m365-automation\atk @microsoft/m365agentstoolkit-cli@1.1.19
dotnet tool install Microsoft.Agents.Hosting.Cli --version 0.2.128-beta --tool-path .easm-agent\tools\m365-automation\msagent
```

Node 20.19/22.12 이상 및 .NET 10이 필요합니다. CLI에서 새 테넌트의 인증을 직접 준비한 뒤 [config.yaml](config.yaml)의 빈 입력을 채웁니다. 비 Windows 환경은 `msagent_executable`에 설치된 네이티브 실행 파일을 지정합니다. 저장소에는 실제 환경 ID·계정·라이선스 영수증을 커밋하지 않습니다.

새 데모는 과거 90일·6개월 이력을 만들지 않습니다. 생성 업무 승인·독립 등록부·인사 대사·실제 노출 조치는 [추가 보고서 증적 계약](../docs/api-notes.md#원본-ppt의-추가-증적과-한계)의 승인 원천이 있어야 채워집니다. 개인 범위 Toolkit 앱이 Power Platform 또는 조직 카탈로그에 인덱싱된다고 가정하지 않으며 코드 배포 검증과 관리자 인벤토리를 구분합니다.

### 실제 Agent Builder UI 작성·인벤토리 검증

코드 기반 기본 데모에는 Agent Builder UI 작성본이 없습니다. Agent Builder 수집을 검증하려면 아래 절차로 별도 생성하고 인벤토리 반영 여부를 확인합니다.

| 순서 | 실제 준비·검증 |
| --- | --- |
| 1 | 승인된 테스트 테넌트·작성자·읽기 사용자·라이선스 확인. `python -m demo.m365 plan`으로 경계 확인 |
| 2 | Microsoft 365 Copilot의 Agent Builder에서 `EASM Demo Builder` 생성. 합성 지침만 사용하고 지식·개인정보·외부 작업은 연결하지 않음 |
| 3 | 코드 데모의 Studio 초안을 사용하거나 별도 테스트 환경에 `EASM Demo Studio` 생성. 합성 지침과 Entra 인증을 사용하고 기본 조직 전체 공유는 피함 |
| 4 | 두 Agent를 테스트 창에서 호출. 게시가 필요하면 라이선스·테스트 사용자 범위를 확인한 뒤 UI에서 게시. 초안 인벤토리 확인과 게시 완료를 구분 |
| 5 | 인벤토리 반영 후 별도 `Global Reader` 또는 `AI Reader` 사용자로 승인된 내보내기 실행 |
| 6 | 인벤토리의 실제 Agent ID·환경을 확인하고 `verify`로 두 작성 도구와 선택적 게시 상태를 검증 |

합성 지침 예: `진단용 합성 Agent입니다. 준비 상태를 물으면 EASM_DEMO_READY라고 답합니다. 실제 데이터나 외부 작업을 사용하지 않습니다.` 모델 응답은 고정 문자열 보장이 아니므로 실제 테스트 결과를 확인합니다.

```powershell
az login --tenant "<테스트 테넌트 ID>"
python scripts\export_copilot_inventory.py --tenant-id "<테스트 테넌트 ID>" --output copilot-inventory.json --approved
python -m demo.m365 verify --inventory-file copilot-inventory.json --tenant-id "<테스트 테넌트 ID>" --agent-builder-id "<실제 Agent ID>" --copilot-studio-id "<실제 Agent ID>"
```

| 옵션·결과 | 의미 |
| --- | --- |
| `--require-published` | 실제 게시 시각이 있는 두 Agent만 통과. 평가판의 테스트 가능과 게시 가능을 혼동하지 않음 |
| `--agent-builder-environment-id` / `--copilot-studio-environment-id` | 환경까지 명시하여 ID가 모호한 경우 구분 |
| `verified`, 종료 0 | 승인된 인벤토리에서 요청한 ID·작성 도구·선택적 게시 상태 확인. 모델 응답·배포·전체 통제 검증은 아님 |
| `not_ready`, 종료 2 | 누락·미게시·조회 실패 등 준비 미완료 |
| 가져오기 | `easm-agent collect --copilot-only --tenant-id "<테넌트 ID>" --copilot-inventory-file copilot-inventory.json` 또는 Azure 수집에 같은 파일 추가 |
| 정리 | 승인된 소유자가 서비스 UI에서 이번에 만든 두 Agent만 확인 후 삭제. 공유·청구·관리 역할 정리는 별도 확인 |

### E7·라이선스 판단

2026-11-18 공식 문서 확인 기준이며 구매·할당은 수행하지 않습니다. 실제 테넌트 계약·서비스 플랜을 확인합니다.

| 목적 | 필요 조건·E7 관계 |
| --- | --- |
| Agent Builder 기본 작성 | 적격 M365/Copilot Chat와 테넌트 정책. 조직 데이터 기반 기능은 Microsoft 365 Copilot 또는 Copilot Studio 종량제 등 기능별 자격 확인 |
| Copilot Studio 작성·게시 | Microsoft 365 Copilot 또는 Studio 사용자·테넌트 용량·종량제 등 선택 경로. 평가판은 테스트 가능하지만 게시 불가 |
| Power Platform 인벤토리 | 위임 사용자·읽기 역할·API 사용 동의 필요. API 문서가 E7 필수를 명시하지 않으므로 필수 처리하지 않음 |
| Agent 365 고급 관측·도구 통제·Graph 등록부 API·보안 거버넌스 | Agent 365 또는 E7 등의 기능별 라이선스 필요. Power Platform 인벤토리와 별도 서비스 |
| E7 | E5 + Microsoft Copilot + Entra Suite + Agent 365 포함. 일괄 도입 선택지이며 이번 데모·수집의 유일한 경로는 아님 |

공식 근거: [개발 자격](https://learn.microsoft.com/en-us/plugins/prerequisites), [Studio 라이선스](https://learn.microsoft.com/en-us/microsoft-copilot-studio/billing-licensing), [E3·E5·E7 비교](https://learn.microsoft.com/en-us/copilot/plan/compare-copilot-e3-e5-e7), [Agent 365 서비스 설명](https://learn.microsoft.com/en-us/office365/servicedescriptions/microsoft-agent-365/microsoft-agent-365).

**이 저장소 변경만으로 SaaS Agent 생성·게시·라이선스 구매·실제 관리자 인증이 완료되지는 않습니다.**

UI·테넌트 없이 출력 경로만 확인하려면 합성 fixture를 사용합니다. 이 파일은 관리자 내보내기나 배포 영수증이 아닙니다.

```powershell
easm-agent collect --fixture tests\fixtures\copilot_agents.json --output-dir output --customer "<데모 고객사>"
```

## 제안 항목별 데모 구성

| 데모 항목 | 위치 | 수집 제안 주제 | 결과가 갈리는 지점 |
| --- | --- | --- | --- |
| 사용자 지정 콘텐츠 필터(RAI) `raiPolicies@2024-10-01`, 기반 `Microsoft.DefaultV2`, Hate 필터 재정의 | [foundry.bicep](foundry.bicep) | RAI 정책 적용 범위 | 주 모델 배포만 사용자 지정 정책, 추가 모델 배포는 기본 정책 |
| Action Group + 메트릭 경고 | [monitor.bicep](monitor.bicep) | 경고 규칙·수신자 구성 | Foundry `AzureOpenAIAvailabilityRate` 99 미만, 웹 앱 `Http5xx` 5 초과 |
| Azure Policy 내장 감사 할당 `policyAssignments@2024-05-01` | [policy.bicep](policy.bicep) | 정책 준수 상태 | Foundry 계정이 `publicNetworkAccess: Enabled`라 비준수 |
| Foundry Agent 함수 도구 1개(`privacy-helper`, prod) | [catalog.json](catalog.json) | Agent 도구 구성 | 함수 스키마만 등록, 실행 없음 |
| Foundry Agent 원격 MCP 도구 1개(`onboarding-helper`) | [catalog.json](catalog.json) | MCP 엔드포인트 호스트 | `learn.microsoft.com/api/mcp`, 승인 `always` |

- **경고:** 그룹마다 1개, 수신자는 구독의 `Monitoring Reader` 역할 보유자입니다. 외부 웹훅은 `WebhookServiceUriBlocked`로 거부되어 사용하지 않습니다.
- **정책:** `DoNotEnforce`·`Audit`만 사용해 차단하지 않습니다. 내장 정의는 Deprecated·기본 `Disabled`이므로 `Audit`를 명시합니다. 첫 구독의 `Microsoft.PolicyInsights` 등록과 평가 반영 대기가 필요합니다.
- **도구 Agent:** `chatbot-v2-tool`로 등록하되 텍스트 답변 없는 도구 호출·승인 요청은 대화·평가에서 제외하고 화면에 409를 표시합니다.
- 같은 세대의 재배포는 삭제 없이 수렴하며 메트릭 경고 규칙의 월 비용이 추가됩니다.

## 챗봇 접속과 안전 경계

`.easm-agent/demo/lab.json`의 `chat_url`에서 **Agent 선택 → 질문 입력 → 질문 보내기**를 사용합니다. 호스트마다 Foundry 8개·자기 LangChain 1개를 표시하므로 중복 목록을 추가 Agent로 세지 않습니다.

| 경계 | 적용·한계 |
| --- | --- |
| 로그인 | 동일 테넌트·허용 사용자 검증. 기본 허용자는 배포 관리자 1명이며 자동 추가 없음. 구성 중 허용자 목록을 비우고 App Service 인증·허용자 설정 확인 후 활성화 |
| 실행 신원 | User Assigned MI 연합 인증, client secret 없음. 모델 호출은 웹 앱 MI이며 진단 SP와 별개 |
| 인바운드 | 배포 자동화는 IP 제한을 구성하지 않음. 필요한 IP 제한은 관리자가 별도로 구성하고 적용 범위를 확인 |
| 호출 제한 | 동시 1개, 사용자별 분당 10회·호스트별 하루 100회. 메시지 2,000자·대화 8,000자·10개 메시지·응답 256토큰. 일일 카운트는 재시작 후 유지하나 비용 상한은 아님 |
| 로그 | 완료 이벤트·Agent ID·토큰 수만 기록. 질문·답변·사용자 ID 미기록. `/health`는 모델 미호출, 익명 채팅 차단 |
| 패키지 | Linux CPython 3.11 wheel과 앱 런타임 파일·의존성만 포함하고 관리자 코드·설정·테스트는 제외. 최초 배포에서는 기본 시작을 유지하고 새 Kudu 배포 ID가 완료된 후 앱 시작 명령을 적용 |
| 평가 | 합성 응답 3문항 정확 일치 검사. 완료·전체 통과·배포 전 평가는 별개이며 종합 안전성·업무 품질 인증 아님 |
| 관측 | 생성 직후 30일 비용·90일 관측 확보 불가. API 미지원·권한 부족·유입 지연은 0·L1로 대체하지 않음 |

## 실행형 거버넌스 데모

| 제어 | 실제 실행 경로 | 한계 |
| --- | --- | --- |
| 외부 endpoint 기본 거부 | 모델 client 생성 전 서버 설정의 `AZURE_OPENAI_ENDPOINT` 또는 `AZURE_AI_PROJECT_ENDPOINT`와 HTTPS 주소를 정확히 대조 | Azure 네트워크 정책이나 원격 Foundry/MCP 도구의 집행 증거는 아님 |
| 합성 작업 승인/거부 | 로그인 사용자가 아래 API로 작업과 결정을 생성하고 LangChain `synthetic_record` 도구가 승인된 ID를 1회 실행 | Azure 쓰기 없음, 메모리 합성 레코드만 사용, 300초 만료, 최대 256개 |
| 버전/자체 검사 | `/health`의 `governance`에 정책/런타임 버전, 코드 해시, 양성/음성 검사 결과 공개 | URL/사용자/대화/작업 ID 없음, 합성 승인 fixture는 실제 사람의 승인이 아님 |

- `langchain-tools` 호스트의 로그인된 동일 사이트 요청만 작업 API를 사용할 수 있습니다. 모델에는 승인 도구를 제공하지 않으며 Foundry 도구 Agent의 기존 409 응답은 유지합니다.
- 브라우저 개발자 도구에서 실제 사용자가 요청합니다. 첫 명령 뒤 승인 또는 거부를 직접 선택하고, 승인했다면 채팅에 `synthetic_record`로 해당 ID를 실행하도록 요청합니다. 실제 고객 데이터는 입력하지 않습니다.

```javascript
const headers = {"Content-Type": "application/json", "X-EASMAgent-Chat": "1"};
const action = await fetch("/api/governance/actions", {
  method: "POST", headers, body: JSON.stringify({value: "synthetic-ready"})
}).then(r => r.json());
// 실제 사용자가 승인하려는 작업 ID인지 확인한 뒤 true 또는 false를 선택합니다.
await fetch(`/api/governance/actions/${action.action_id}/decision`, {
  method: "POST", headers, body: JSON.stringify({approved: true})
});
console.log(action.action_id);
```

### 로컬 테스트와 배포 후 검증

```powershell
.\.venv\Scripts\python.exe -m pytest demo\test_governance.py -q --basetemp=.easm-agent\pytest-governance
.\.venv\Scripts\python.exe -m ruff check demo\governance.py demo\test_governance.py demo\app.py
```

1. 배포 패키지에 `governance.py`를 `app.py`와 같은 위치에 포함합니다.
2. 승인된 기존 배포 절차로 배포하고 새 배포 ID의 성공을 확인합니다.
3. 실제 HTTPS `/health`를 읽고 `governance.passed`, 10개 검사, `configured_endpoint_count` 및 버전/코드 해시를 확인합니다. 로컬 `runtime_code_digest()`와 일치해야 합니다.
4. 로그인 후 합성 작업의 승인 전 거부, 명시적 거부, 명시적 승인 후 1회 성공, 재실행 거부를 확인합니다. 원격 Foundry/MCP 승인은 별도 검증 대상입니다.

| 검증 대상 | 진입점·확인값 |
| --- | --- |
| 승인 배포 | `python -m demo.agents --apply`. `expand()`는 로그인·Agent·패키지 배포·실제 호출을 수행하므로 관리자 승인 필수. 동일 버전 성공 영수증은 재사용 가능 |
| 실제 호출 | [sample_response](agents.py) 또는 [invoke_agent](app.py). 후자는 `/api/chat`에서 MI 사용. 합성 프롬프트만 사용하고 Agent ID·버전·응답·시각·호스트 경로 대조 |
| 평가 | [evaluate_agent](agents.py)의 `agent_id`·`agent_version`·`run_id`·`status`·완료 시각·통과 항목 확인. `expand()`는 endpoint 연결 후 평가하므로 배포 전 평가 증거가 아님 |
| 시각·사용량 | `chatbot-expansion/<lab_id>/state.json`의 `published_at`은 관리자 영수증. 버전 생성 시각·계정 전체 토큰 수를 운영 배포·사용 이력으로 해석하지 않음 |

### 수집 결과와 API 등급

| 구분 | 사용 방법 |
| --- | --- |
| 등급 기준 | `config/criteria.yaml`의 API 필드·분모·비율 규칙 적용 |
| 수집 실행 | `python -m demo.manage collect`로 실제 Azure API 구성·기록을 수집 |
| 데모 런타임 | `/health`의 코드 해시·검사 결과와 성공한 배포 ID를 대조. API 구성 등급과 실행 시험 결과는 구분 |

- 완료 평가 실행은 프로젝트 평가 이력으로 집계하며 버전 생성 시각을 운영 배포 시각으로 간주하지 않습니다.
- 예산은 현재 유효 기간·무필터 범위·실제/예측 경보·수신자 구성을 API에서 대조하며 실제 알림 전달이나 지출 차단을 뜻하지 않습니다.

![실제 로그인 동의 - 식별자 마스킹과 클릭 위치](imgs/01-entra-consent.png)

![실제 LangChain 챗봇 대화](imgs/02-langchain-chat.png)

![실제 Foundry 챗봇 대화와 평가 조건](imgs/03-foundry-chat.png)

- 캡처는 최초 검증 당시 화면이며 새 배포의 완료 증거로 재사용하지 않습니다. [캡처 범위](../docs/manifest.json)를 참고하세요.

## 개발 검사와 정리

```bash
python -m pip install -e ".[dev,demo]"
python -m pytest -q
python -m ruff check src scripts demo tests
python -m demo.manage cleanup
```

- `cleanup` 기본값은 목록 확인만 하는 dry-run입니다. 실제 그룹 삭제에는 별도 승인과 `--apply --confirm-lab-id '<lab_id>'`가 필요합니다.
- 대상 테넌트와 모든 그룹의 소유 태그를 먼저 확인합니다. 기존 앱/SP·역할 정의·다른 고객 리소스는 삭제하지 않습니다.
