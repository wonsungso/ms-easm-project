# 개발용 데모

**고객 진단에는 필요하지 않습니다.** 고객 절차는 [README](../README.md), API·권한 근거는 [API 참고](../docs/api-notes.md)를 따릅니다. 관리자 배포와 Reader SP 수집은 분리하며 수집기는 `demo`를 import하지 않습니다.

## 배포와 실행

| 준비·범위 | 내용 |
| --- | --- |
| 실행 위치·권한 | 프로젝트 루트, 승인된 관리자, `.easm-agent/setup.json` |
| 입력 | `tenant_id`·`subscription_ids`·`account_name`, [config.yaml](config.yaml) |
| 배포 대상 | 소유 태그가 있는 별도 그룹의 Foundry·모델·웹 앱·로그. [catalog.json](catalog.json): Foundry 8개·LangChain 2개 |
| 승인 조건 | Korea Central·소형 모델·합성 데이터, GlobalStandard 처리·공급자 등록 승인 |
| 진단 SP | 별도 준비. 없으면 진단 역할 생성·할당 생략 |

```bash
bash scripts/setup.sh login
bash demo/run.sh --apply
```

- 인프라·로그인 보호 챗봇 10개·실제 평가 4건을 준비·유지합니다. 진단 SP 생성·수집은 별도이며 통합 수집은 SP 준비 후 `bash demo/run.sh --apply --collect`로 실행합니다.
- 배포 전 테스트·Ruff·Bicep·구독별 ARM validate/what-if·정책 조회를 수행합니다. 삭제 계획이 있으면 중단하고 검증 증거는 `.easm-agent/demo/validation.json`에 저장합니다.
- **비용이 발생합니다.** B1 2개 USD 0.036/시간은 과거 검증값이며 모델·로그는 별도입니다. 설정의 USD 100은 승인 예산이지 과금 상한이 아닙니다.

## 개별 명령과 실패 후 재개

| 목적 | 프로젝트 루트에서 실행 |
| --- | --- |
| 계획·테스트 | `python -m demo.manage plan` / `python -m demo.manage test` |
| 사전 검증 | `python -m demo.manage validate --prepare-providers` |
| 인프라 재사용 배포 | `python -m demo.manage deploy --apply --reuse-infrastructure` |
| Agent·웹 앱 배포 | `python -m demo.agents --apply` |
| Reader 수집 | `python -m demo.manage collect` |
| 기존 결과 검증 | `python -m demo.diagnostics verify` |
| Codespaces 검증 | `python -m demo.diagnostics codespace --codespace '<Codespace 이름>' --apply` |

- **재개:** 실패한 단계만 같은 명령으로 실행합니다. `.easm-agent/demo/`의 `lab.json`·`runthrough.json`·`chatbot-expansion/` 영수증을 확인합니다. 재사용 배포도 소유 태그·검증 증거를 확인하며 없는 리소스를 임의 생성하지 않습니다.
- **인증:** `collect`는 임시 공개 인증서·저장소 밖 개인키를 사용합니다. 종료 시 새 인증서만 정리하며 강제 종료 시 잔여 여부를 확인합니다.
- **권한:** 실제 거부 확인 시에만 설정에 따라 Cost Management Reader·작업 영역 Log Analytics Reader를 추가합니다. `auto_grant_needed_read_roles: false`로 비활성화할 수 있으며 관리자 수집으로 대체하지 않습니다.
- **결과:** 실행별 `output/<실행시각-UTC>/`를 보존합니다. [출력 형식](../README.md#step-4)은 공통이며 종료 코드 `2`의 자료 미확보 사유도 유지합니다.
- **검증:** `verify`는 전체 통합 수집 결과·역할·인증서 잔여 수·HTTP 상태를 읽고 테스트하며 배포·추론·역할 변경은 하지 않습니다.

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
| 로그인 | 동일 테넌트·허용 사용자 검증. 기본 허용자는 배포 관리자 1명이며 자동 추가 없음 |
| 실행 신원 | User Assigned MI 연합 인증, client secret 없음. 모델 호출은 웹 앱 MI이며 진단 SP와 별개 |
| 인바운드 | App Service 1개에 승인 공인 IP 허용·기본 거부. 범위 밖 로그인·`/health`도 차단. SCM·다른 워크로드 유지. 기록: `.easm-agent/demo/network-boundary-20261109.json` |
| 호출 제한 | 동시 1개, 사용자별 분당 10회·호스트별 하루 100회. 메시지 2,000자·대화 8,000자·10개 메시지·응답 256토큰. 일일 카운트는 재시작 후 유지하나 비용 상한은 아님 |
| 로그 | 완료 이벤트·Agent ID·토큰 수만 기록. 질문·답변·사용자 ID 미기록. `/health`는 모델 미호출, 익명 채팅 차단 |
| 패키지 | Linux CPython 3.11 wheel과 앱 런타임 파일·의존성만 포함. 관리자 코드·설정·테스트 제외. 새 Kudu 배포 ID 완료·실제 모델 응답 각각 검증 |
| 평가 | 합성 응답 3문항 정확 일치 검사. 완료·전체 통과·배포 전 평가는 별개이며 종합 안전성·업무 품질 인증 아님 |
| 관측 | 생성 직후 30일 비용·90일 관측 확보 불가. API 미지원·권한 부족·유입 지연은 0·L1로 대체하지 않음 |

## 실행형 거버넌스 데모

| 제어 | 실제 실행 경로 | 한계 |
| --- | --- | --- |
| 외부 endpoint 기본 거부 | 모델 client 생성 전 서버 설정의 `AZURE_OPENAI_ENDPOINT` 또는 `AZURE_AI_PROJECT_ENDPOINT`와 HTTPS 주소를 정확히 대조 | Azure 네트워크 정책이나 원격 Foundry/MCP 도구의 집행 증거는 아님 |
| 합성 작업 승인/거부 | 로그인 사용자가 아래 API로 작업과 결정을 생성하고 LangChain `synthetic_record` 도구가 승인된 ID를 1회 실행 | Azure 쓰기 없음, 메모리 합성 레코드만 사용, 300초 만료, 최대 256개 |
| 버전/자체 검사 | `/health`의 `governance`에 정책/런타임 버전, 코드 해시, 양성/음성 검사 결과 공개 | URL/사용자/대화/작업 ID 없음, 합성 승인 fixture는 실제 사람의 승인이 아님 |

- `langchain-tools` 호스트의 로그인된 동일 사이트 요청만 작업 API를 사용할 수 있습니다. 모델에는 승인 도구를 제공하지 않습니다. Foundry 도구 Agent의 기존 409 응답은 유지합니다.
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

1. 배포 패키지에 `governance.py`를 `app.py`와 같은 위치에 포함합니다. 이 파일 추가만으로 배포가 완료되지는 않습니다.
2. 승인된 기존 배포 절차로 배포하고 새 배포 ID의 성공을 확인합니다.
3. 실제 HTTPS `/health`를 읽고 `governance.passed`, 10개 검사, `configured_endpoint_count` 및 버전/코드 해시를 확인합니다. 로컬 `runtime_code_digest()`와 일치해야 합니다.
4. 로그인 후 합성 작업의 승인 전 거부, 명시적 거부, 명시적 승인 후 1회 성공, 재실행 거부를 확인합니다. 원격 Foundry/MCP 승인은 별도 검증 대상입니다.

| 검증 대상 | 진입점·확인값 |
| --- | --- |
| 승인 배포 | `python -m demo.agents --apply`. `expand()`는 로그인·Agent·패키지 배포·실제 호출을 수행하므로 관리자 승인 필수. 동일 버전 성공 영수증은 재사용 가능 |
| 실제 호출 | [sample_response](agents.py) 또는 [invoke_agent](app.py). 후자는 `/api/chat`에서 MI 사용. 합성 프롬프트만 사용하고 Agent ID·버전·응답·시각·호스트 경로 대조 |
| 평가 | [evaluate_agent](agents.py)의 `agent_id`·`agent_version`·`run_id`·`status`·실제 완료 시각·통과 항목 확인. `expand()`는 endpoint 연결 후 평가하므로 배포 전 평가 증거가 아님 |
| 시각·사용량 | `chatbot-expansion/<lab_id>/state.json`의 `published_at`은 관리자 영수증. 버전 생성 시각·계정 전체 토큰 수를 Agent 운영 배포·사용 이력으로 해석하지 않음 |

### 수집 결과와 API 등급

| 구분 | 사용 방법 |
| --- | --- |
| 등급 기준 | `config/criteria.yaml`의 API 필드·분모·비율 규칙 적용 |
| 수집 실행 | `python -m demo.manage collect`로 실제 Azure API 구성·기록을 수집 |
| 데모 런타임 | `/health`의 코드 해시·검사 결과와 성공한 배포 ID를 대조. API 구성 등급과 실행 시험 결과는 구분 |
| 이전 검증 도우미 | `generate_policy_facts`는 과거 데모 검증 호환용이며 현재 API 등급 입력으로 사용하지 않음 |
| 저장 파일 | `read_collection_file(path)`는 원본 JSON의 Collection과 첨부 증적을 읽음. 잘못된 스키마는 오류 |

- 완료 평가 실행은 프로젝트 평가 이력으로 집계합니다. 버전 생성 시각을 운영 배포 시각으로 간주하지 않습니다.
- 예산은 현재 유효 기간·무필터 범위·실제/예측 경보·수신자 구성을 API에서 대조합니다. 실제 알림 전달이나 지출 차단을 뜻하지 않습니다.

![실제 로그인 동의 - 식별자 마스킹과 클릭 위치](imgs/01-entra-consent.png)

![실제 LangChain 챗봇 대화](imgs/02-langchain-chat.png)

![실제 Foundry 챗봇 대화와 평가 조건](imgs/03-foundry-chat.png)

- 캡처는 최초 검증 당시 화면입니다. 새 배포의 완료 증거로 재사용하지 않습니다. [캡처 범위](../docs/manifest.json)를 참고하세요.

## 개발 검사와 정리

```bash
python -m pip install -e ".[dev,demo]"
python -m pytest -q
python -m ruff check src scripts demo tests
python -m demo.manage cleanup
```

- `cleanup` 기본값은 목록 확인만 하는 dry-run입니다. 실제 그룹 삭제에는 별도 승인과 `--apply --confirm-lab-id '<lab_id>'`가 필요합니다.
- 대상 테넌트와 모든 그룹의 소유 태그를 먼저 확인합니다. 기존 앱/SP·역할 정의·다른 고객 리소스는 삭제하지 않습니다.

<details>
<summary>이전 실제 실행 기록 - 새 실행의 완료 근거 아님</summary>

| 실행 | 당시 확인한 결과 |
| --- | --- |
| 이전 통합 수집 | Reader SP·Codespaces 수집·XLSX·ZIP·증거 링크 확인. 자료 부족은 보류, 임시 키·인증서 정리. 해당 진단 SP는 삭제됨 |
| 2026-11-04 배포 범위 | 승인된 데모 인프라·챗봇만 생성. 진단 SP·역할·수집은 미수행, 타 업무·soft-delete 항목 삭제 없음 |
| 배포 전 검증 | 01:00:23Z - 01:03:28Z 종료 0. 테스트 227개·Ruff·Bicep·ARM validate/what-if·정책 조회 통과, 삭제 계획 없음 |
| 배포·호출 | `demo-redeploy-20261104`·lab `98faf4dd7e`: 01:50:30Z 모든 구독 `Succeeded`. Foundry 8개·LangChain 2개·평가 4건·모델 응답 확인 |
| 인증·회귀 | 두 앱 health 200·익명 채팅 401, MI의 OpenAI User·Foundry User 확인. 연합 인증·비밀 없음. 일시 오류 후 멱등 재개, 최종 228 passed·1 skipped |

상태·주소·실측 영수증은 Git 제외 `.easm-agent/demo/`에 보존합니다. 위 기록은 새 배포의 완료 증거가 아닙니다.

</details>
