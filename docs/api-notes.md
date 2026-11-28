# API·평가 기준 참고

| 찾을 내용 | 위치 |
| --- | --- |
| 실행·권한 설정·정리 | [README](../README.md) |
| 항목별 점검 내용·확인 화면 | [점검 항목 상세](checklist.md) |
| 지표·분모·증거·한계·등급 규칙 | [criteria.yaml](../config/criteria.yaml) |
| 이기종 Agent 연결 | [이기종 에이전트 설정](connected-platforms.md) |

## 범위 원칙

| 구분 | 내용 |
| --- | --- |
| 실행 신원 | 진단 SP의 `DefaultAzureCredential`, Reader 중심 GET·읽기 query POST |
| 수집 범위 | 지정 테넌트의 접근 가능한 구독 또는 승인 범위. 외부 workspace·청구 범위로 확대하지 않음 |
| 관리자 예외 | `scripts/setup.sh`·`setup_account.py`·정리 스크립트와 demo만 승인된 배포·역할·일회성 인증 준비를 수행하며 수집기는 import하지 않음 |
| Agent 집계 범위 | Foundry·Copilot Studio·Agent Builder의 플랫폼 API 및 Agent 365 연결 에이전트 |
| 구독별 읽기 범위 | 완료된 인벤토리에 Azure AI 리소스가 없는 구독의 비용·보안은 증적과 함께 범위 제외. 조회 실패·비용 행 누락을 범위 제외로 바꾸지 않음 |
| 관리자 입력 | 환경·DLP는 별도 승인된 관리자 API 내보내기를 사용. 평가 이력은 `--include-evaluations`로 읽고, Standard 조회 앱의 403은 동일 대상에 연결된 공식 CLI 읽기로 확인 가능 |
| API 샘플 배포 | Foundry `azure-ai-projects`의 `create_version`·`update_details`, Copilot Studio Preview `msagent agent create/deploy` 후 Dataverse `PvaPublish`·게시 시각 대사. Agent Builder의 UI 작성 출처를 Toolkit으로 대체하지 않음 |
| 제외 | Red team·조건부 접근·위험 Agent는 26개 등급 제외. Azure Public만 지원 |
| 용어·개인정보 | MS Learn 용어 사용. API 키·리소스 이름은 유지하며 비밀·토큰·사람 정보는 마스킹 |

## 평가 규칙

### Agent 365 공통 등록부

평가 지표·분모·조건은 기본 [criteria.yaml](../config/criteria.yaml)에 정의합니다. 결과에는 사용한 기준 사본·해시·평가 시각을 저장합니다.

| 항목 | 구성·기록 조건 |
| --- | --- |
| DM-SY-01 | 등록 ID·지원 플랫폼·생성 시각 |
| DS-SY-03 | 플랫폼·패키지 유형. 이기종은 연결 등록 유형·공급자·원본 저장소도 확인 |
| BI-SY-08 | 이기종 원본 PublishedStatus 또는 MS 등록부 deployedTo의 명시된 상태 |
| BI-SY-10 | isBlocked의 명시적 true·false. 안전성·차단 효과를 평가하지 않음 |
| BI-SY-13 | MS 설명 또는 이기종 실행 지침의 비어 있지 않음만 선별 저장. 원문 미저장 |
| BI-SY-14 | 명시된 배포 범위. 일부 배포는 대상 목록이 확인되고 1개 이상이어야 함 |
| OE-SY-16 | 등록부 소유자 1개 이상. BI-SY-13과 중복 평가하지 않음 |
| OE-SY-17 | 허용·배포·공유 대상 건수 및 사용자·그룹별 합계 일치 |
| OE-SY-18 | 동일 테넌트·완료된 두 API 목록, 시각 순서·현재 관측 시각·대상별 비교 확인 |
| OT-SY-23 | 생성·수정 시각 확인 및 `생성 <= 수정 <= Agent 365 관측 시각`. 사용량·휴면·정기 동기화 아님 |

MS·이기종 공통 항목은 Agent 365, 나머지는 플랫폼 API로 측정합니다. 등록 패키지 수와 직접 관측 Agent 수는 별도 단위입니다. 앱·도구·미귀속 패키지는 제외하며 필수 필드 미확인은 `null`입니다.

### 공통 등급

충족률 = 전체 분모 중 API 증거가 조건을 충족한 비율입니다. 비용(OT-SY-24)만 건수가 아닌 금액 기준입니다.

| 충족률 | Level | 점수 |
| --- | --- | --- |
| 0% | L1 | 1 |
| 0% 초과~80% 미만 | L2 | 2 |
| 80% 이상~90% 미만 | L3 | 3 |
| 90% 이상~100% 미만 | L4 | 4 |
| 100% | L5 | 5 |

| 규칙 | 내용 |
| --- | --- |
| 완전성 | 전체 인벤토리·페이지·관련 조회·필수 필드를 확인한 뒤 계산. 일부 성공 응답으로 전체 비율을 만들지 않음 |
| 판정 불가 | 조회 실패·필수 필드 미확인·빈 분모는 `null`과 표준 사유(`permission_denied`, `feature_unavailable`, `license_missing`, `not_found`, `error`). L1·0%로 바꾸지 않음 |
| L1 | 유효한 양수 분모에서 확인된 충족률 0%에만 적용. 조회 완료 후 명시적으로 비어 있는 경우와 조회 실패를 구분 |
| 해석 한계 | L5도 구성·기록의 비율이며 정책 승인·실효성·조직 성숙도 아님. 403 원인은 별도 확인 |
| 고객 입력 | `policy_facts`·허용 모델 등 과거 Settings 필드는 설정 로딩 호환용이며 등급에 사용하지 않음 |
| 기준 변경 | 지표·임계값·기간은 `criteria.yaml`, 수집 기술 설정은 선택 `custom-config.yaml`. `--criteria`로 별도 기준 지정 |
| 기간 | `criteria.yaml`의 보존·관측·비용 기간 적용. 등록정보 시각과 사용량 기간은 구분 |
| 재현성 | `findings[].evidence_refs`·`measurement`(분자·분모·통화·보류 사유)·`measurement.targets[]`·`provenance.references`(SHA256)·`collection.assessment_provenance`(기준 사본·수집기 버전 해시)에 보존. 해시는 원천 서명이 아님 |
| 재평가 | `package`는 저장 판정을 유지. 새 기준·관리자 증적은 `--reassess`로 반영하며 원래 수집 시각과 `origin=saved_snapshot_reassessment`를 기록 |

## 읽기 API (Azure)

모두 읽기 전용이며 구독별 병렬 실행·전체 페이지·429/일시 오류 재시도·부분 실패 기록을 유지합니다. 증적은 저장 전에 비밀·토큰·연결문자열·개인 식별 정보를 마스킹합니다.

| 조회 | 경로·버전 | 한계 |
| --- | --- | --- |
| 구독 | GET `/subscriptions`, `2022-12-01` | Enabled 구독 |
| 유효 권한 | `Microsoft.Authorization/permissions`, `2022-04-01` | 쓰기 권한 안전 가드이며 IAM 감사 아님 |
| 리소스 | `/subscriptions/{id}/resources`, `2021-04-01` + Resource Graph | nextLink 처리 |
| 신규 Agent | project endpoint `/agents`, `/agents/{name}/versions`, `api-version=v1` | 논리 Agent당 1건. 최신 버전이 운영 배포라고 주장하지 않음 |
| 평가 | `/openai/v1/evals`, `/openai/v1/evals/{id}/runs` | 완료 이력만. 질문·응답·데이터셋 미조회. 완료 시각이 없으면 생성 시각으로 대체하지 않음 |
| 모델 배포 | `{account}/deployments`, `2024-10-01` | 구성값이며 모델 승인 아님 |
| 콘텐츠 필터 | `{account}/raiPolicies`, `2024-10-01` | 정책명 미지정은 필터 부재가 아님(기본 필터 존재 가능) |
| ARM 역할 | `Microsoft.Authorization/roleAssignments`, `2022-04-01` | 관리 ID 직접 할당과 Graph 앱 역할을 구분 |
| Resource Graph | 읽기 query POST, `2022-10-01` | Resources·PolicyResources·SecurityResources. 빈 결과는 Defender 활성화 증거가 아님 |
| 진단 설정 | `{resourceId}/providers/Microsoft.Insights/diagnosticSettings`, `2021-05-01-preview` | Agent 관련 로그만. 구독 Activity Log 제외 |
| workspace | `{workspaceResourceId}`, `2022-10-01` | 설정 보존값이며 테이블별 유효 보존이 아님. 승인 구독 밖은 `permission_denied` |
| 메트릭 | `{resourceId}/providers/Microsoft.Insights/metrics`, `2018-01-01` | 숫자 표본 확인. timespan은 UTC `Z` 형식 |
| 비용 | `Microsoft.CostManagement/query`, `2023-03-01` | Daily·ResourceId·UsageDate·Cost·Currency. 공유 비용 중복 귀속 금지 |
| 예산 | `Microsoft.Consumption/budgets`, `2023-05-01` | amount·category·timePeriod·filter·notifications. 수신자는 존재·개수만 저장 |
| 작업 그룹 | `{actionGroupResourceId}`, `2021-09-01` | 활성 수신자 유형 대조. 전달 성공 아님 |
| Defender 플랜 | `Microsoft.Security/pricings`, `2024-01-01` | OT-SY-25. AI·CloudPosture 플랜 Standard와 SensitiveDataDiscovery 확장 |
| 보안 점수·정책 할당 | `secureScores 2020-01-01`, `policyAssignments 2023-04-01` | 참고용이며 등급에 미사용 |

| 해석 주의 | 내용 |
| --- | --- |
| 네트워크 | 명시 DefaultAction 우선. 미지정 시 규칙 0개는 허용·1개 이상은 암묵 거부. Any·전체 CIDR Allow와 VNet 통합은 인바운드 경계 증거 아님 |
| 도구·모델 | MCP 승인·HTTPS·허용 도구·업데이트 옵션은 실행 우회 방지·퇴역 대응 보장 아님 |
| 권한 | 쓰기·전체 제어 패턴은 `criteria.yaml` 기준. 비일치가 최소 권한 인증은 아님 |
| 정책·예산 | Audit·Deny·Modify·DeployIfNotExists 구분. 예산은 통보 수단이며 자동 지출 차단 아님 |

### Foundry 역할

[Foundry RBAC](https://learn.microsoft.com/azure/foundry/concepts/rbac-foundry)의 Reader는 관리 평면만 허용합니다. 진단에는 `EASMAgent Foundry Evidence Reader v2`의 `agents/read`·`evaluations/read`·`assets/read`만 사용합니다. `agents/read`에 threads·messages 읽기가 포함되며 더 세밀한 DataAction은 확인되지 않았습니다.

`classic_v1`은 `/assistants?api-version=v1`·초기 평가 `2025-05-15-preview`를 명시적으로 사용합니다. `Foundry User`·`listkeys`·Red team 쓰기 권한은 진단 계정에 부여하지 않습니다.

### Entra Agent ID

| 조회 | Graph v1.0 GET·권한 |
| --- | --- |
| Blueprint | `/applications/microsoft.graph.agentIdentityBlueprint`, `AgentIdentityBlueprint.Read.All` |
| Agent ID | `/servicePrincipals/microsoft.graph.agentIdentity`, `AgentIdentity.Read.All` |
| 소유자·스폰서 | `/servicePrincipals/{id}/microsoft.graph.agentIdentity/owners`·`sponsors`. 이름·UPN 없이 관계 수만 보관. `accountEnabled`는 등급 조건에 사용하지 않음 |
| 앱 역할 | `/servicePrincipals/{id}/appRoleAssignments`, `Application.Read.All`. 대상 SP의 `appRoles`로 이름 해석 |

`Directory.Read.All`은 사용하지 않습니다. ARM 관리 ID와 Graph Agent ID를 구분하며 토큰은 `graph.microsoft.com`에만 보냅니다.

## Copilot 인벤토리

Agent Builder·Copilot Studio를 별도 `copilot_agents`로 수집하고, 모델·접근·도구·평가·보안·게시·신원·소유자·인증 항목에 플랫폼별로 반영합니다.

| 구분 | 계약 |
| --- | --- |
| API | `POST https://api.powerplatform.com/resourcequery/resources/query?api-version=2024-10-01`, `PowerPlatformResources`의 `microsoft.copilotstudio/agents`. 쓰기·배포 API 없음 |
| 인증 | 위임 사용자만 가능(SP·관리 ID는 403). 별도 사용자의 `Global Reader` 또는 `AI Reader`이며 진단 SP에 부여하지 않음 |
| 페이지 | `Options.Top/SkipToken`. 반복 토큰·잘림·건수 불일치·중복은 실패. `resultTruncated`는 정수 enum(`0=잘림`, `1=잘림 아님`) |
| 저장 | 최소 필드만. 소유자는 존재 여부만, 사용자 ID·콘텐츠·토큰 제외. 커넥터는 connectorId·operationId·isEnabled·requiresEndUserConsent 등만 보존하고 200개 제한·건수 불일치는 보류 |
| 작성 도구 | `createdIn`의 `Microsoft Copilot Agent Builder`·`Microsoft 365 Copilot Agent Builder`·`Copilot Studio Lite`만 Agent Builder로 분류. 값 목록은 공식 스키마에 없어 변경될 수 있으며 미확인은 `unclassified_copilot` |
| 범위 | V2 Agent의 게시 버전 구성. V1 봇 제외. 반영 지연은 대체로 20분 이내이며 리소스 종류별 capability 200개 제한이 있어 완전한 도구 분석이 아님 |
| Agent Builder 신원 | 공식 스키마에 Agent ID·청사진 필드가 없어 제외하며 통제 실패로 채점하지 않음 |
| 소유자·ID | `properties.name`(Bot ID)이 있으면 사용하고 null이면 최상위 `name` 사용. 소유자 존재의 정수 `1`/`0`만 Boolean으로 변환 |
| 기존 평가 GET | `/copilotstudio/environments/{EnvironmentId}/bots/{BotId}/api/makerevaluation/testruns`, `2024-10-01`. ID·state·endTime·totalTestCases만 보존. 성공한 빈 목록은 평가 0건, 실패는 `null`과 사유. 새 평가 POST 금지 |
| 평가 위임 권한 | 403 `InsufficientDelegatedPermissions`의 필수 scope는 `CopilotStudio.MakerOperations.Read`. Azure CLI 앱은 `AADSTS65002`이므로 이 권한만 구성한 단일 테넌트 공용 읽기 앱과 현재 사용자 동의를 사용(테넌트 전체 동의·비밀·인증서·진단 SP 변경 없음) |
| 하니스 | Standard 외 하니스는 공식 범위를 보장하지 않음. GitHub Copilot·Copilot Chat은 별도 읽기 앱으로 200·빈 목록을 관측했으나 다른 테넌트·하니스의 지원을 보장하지 않음. 실제 `No evaluation run` 화면은 평가 0건 근거로만 사용 |
| 검토 화면 파일 | `--copilot-review-file`: `schema_version=1`, `source_type=official_admin_portal_read`, `approved`·`tenant_verified=true`, 각 행의 agent_id·environment_id·source_url·observed_at·`state=authoring`. 최근 24시간·중복·테넌트 검증. API 완료 실행과 화면 평가 없음이 상충하면 판정 보류 |
| 실패 | 403만으로 라이선스 부재를 추론하지 않으며 명시적 `not licensed`만 `license_missing`. `collect --copilot-only`는 Azure·Graph에 접근하지 않음 |

Copilot 구성은 정책 승인·실제 모델 버전·처리 지역·보존 준수의 증거가 아닙니다. 공식 근거: [인벤토리 API](https://learn.microsoft.com/en-us/power-platform/admin/inventory-api) · [스키마](https://learn.microsoft.com/en-us/microsoft-copilot-studio/admin-agent-inventory) · [평가 GET](https://learn.microsoft.com/en-us/rest/api/power-platform/copilotstudio/bots/list-maker-evaluation-test-runs) · [하니스](https://learn.microsoft.com/en-us/microsoft-copilot-studio/harnesses-overview).

## Agent 365 카탈로그

| 구분 | 계약 |
| --- | --- |
| API | `GET https://graph.microsoft.com/v1.0/copilot/admin/catalog/packages` 목록과 `/{id}` 상세. 패키지별 GET만 수행하고 `beta` API는 호출하지 않음 |
| 실행 | `collect --agent365-registry` 또는 `agent365_registry: true`. 기본 비활성 |
| 권한·라이선스 | `CopilotPackages.Read.All` 애플리케이션 권한·관리자 동의, Microsoft Agent 365 라이선스(E7 포함). 선택 부여는 관리자 `setup.sh --agent365-reader`. 진단 SP에 디렉터리 관리자 역할을 부여하지 않음 |
| 범위 | 기본 응답의 Agent 포함 패키지. 고유 Agent 수·초안 전체와 다름 |
| 30일 사용 지표 | `activeUsers`·`totalSessions`·`totalRunTimeInHours`·`exceptionRate`(예외 수)·`lastUsedDateTime`. 사용자 수는 합산하지 않고, 호출 수·토큰·비용·가용률로 변환하지 않음. 미제공은 미확인이며 미사용·폐기의 증거가 아님 |
| 분류 메타데이터 | `type`·`manifestVersion`·`appId`·`supportedHosts`·`elementTypes`·`categories`·`sensitivity`. 개인정보 보호를 위해 공식 enum·예시 값만 원문 저장하고 그 밖의 값은 `null/feature_unavailable`. `sensitivity`는 Purview 민감도 레이블 적용·DLP 집행의 증거가 아님 |
| 필드 불일치 | 문서는 `governanceMetadata`를 문자열로 명시하나 실제 응답은 `{"agenticType": "<값>"}`. 키가 `agenticType` 하나이고 값이 문서 열거값이면 사용하고, 그 밖의 형식은 원문 미저장·`null`/`error`로 기록하며 검증된 다른 필드는 유지 |
| 검증·부분 실패 | Int32 비음수·유한 비음수 Double·시간대 있는 날짜만 허용. 형식 오류는 해당 필드만 `null/error`, 누락은 `null/not_found`. 상세 ID·버전이 목록과 다르면 연결하지 않음 |
| 완료 플래그 | `detail_read_completed`는 GET의 ID·버전 검증, `detail_complete`는 30일 사용 필드 전체 확인, `metadata_complete`는 분류 필드 전체 확인. 어느 것도 모집단·관측기간 완전성이 아님 |
| 대규모 보호 | 상세 GET은 순차 실행. 숫자 `Retry-After` 대기·지수 백오프, 재시도 소진 429/5xx·60초 초과 대기 지시·비숫자 `Retry-After`는 남은 상세 중단. 상세 단계 600초 초과 시 새 요청 중단, 연속 5건 실패 시 나머지 중단. 중단 원인과 후보·시도·완료·미조회 수는 `facts.agent365_detail_collection`에 기록 |
| 기간·개인정보 | `usage_window_days=30`, 원천 기간은 `null`이며 순차 수집을 같은 시점 스냅샷으로 표시하지 않음. 사용자·그룹·연락처·소유자 ID·설명·본문·원본 오류는 저장하지 않음 |
| 집계 단위 | 패키지 수는 고유 Agent 수가 아니며, 분포는 필드가 확인된 패키지 기준. 일부만 확인되면 부분 관측으로 표시하고 전체 비율은 `null` |

공식 근거: [List packages](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/admin-settings/package/copilotpackages-list), [Package details](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/admin-settings/package/copilotpackagedetail-get), [Agent 365 Graph API](https://learn.microsoft.com/en-us/microsoft-agent-365/admin/graph-api), [Agent 365 라이선스](https://learn.microsoft.com/en-us/office365/servicedescriptions/microsoft-agent-365/microsoft-agent-365).

### 이기종 Agent

등록 패키지 ID·원본 Agent ID·Entra `agentIdentityId`는 별개입니다. 공통 `Agent ID 보유`는 각 플랫폼 원본 ID(Copilot Bot ID, Foundry Agent ID, AWS·Snowflake SourceAgentId)로 집계합니다. Entra ID는 별도 열이며 미제공을 원본 ID 부재로 취급하지 않습니다. 외부 원본 ID·연결 ID는 SHA256으로 보존합니다.

| 플랫폼 상태 | 보고서 확인 기준 | 한계 |
| --- | --- | --- |
| Foundry | Agent 생성·등록 조회 | 실제 배포·채널 게시·실행 성공은 별도 |
| Copilot | 게시 시각 | 게시와 실제 활동은 별개 |
| AWS·Snowflake | Agent 365 등록 패키지와 원본 ID 연결 | 원본 Published 상태는 별도 보존. 원본 서비스 실행 성공 아님 |

Foundry 생성·프로젝트 호출과 M365·Teams 게시는 별개입니다. [공식 객체 모델](https://learn.microsoft.com/azure/foundry/agents/how-to/migrate-agent-applications).

| 추가 원천데이터 | 저장·표시 |
| --- | --- |
| 연결 정의 | 게시 상태, 원본 버전·상태·유형, 생성·수정 시각, 모델·리전, endpoint HTTPS 판정, 원본·런타임·DB·스키마 식별자 SHA256 |
| 대상·콘텐츠 | 허용·설치·공유 대상 수만 저장. 지침·설명·관리자 문자열은 존재 여부만 보존 |
| 상세 필드 조사 | 공식 상세 속성별 존재·빈 값·누락·원문 제외·최소화 여부. 미확인 사용자 지정 키·정의 본문·ZIP·사람 정보는 미저장 |
| 결과 위치 | `1a_플랫폼 기준`의 Agent ID·플랫폼 상태, `2_SE 원천데이터` 26개 항목의 통합 측정값·주석, `2b_세부 내역` 전체 Agent 상세. 원천 메타데이터 전체는 근거·JSON에 보존 |

도구 등록부는 Graph v1.0 목록의 `elementTypes/any(e:e eq 'AgentConnectors' or e eq 'AgentSkills')`로 별도 읽고 Agent 수에 합산하지 않습니다. 혼합 패키지는 Agent·도구 양쪽에 나타날 수 있으며 특정 외부 Agent의 도구로 추정하지 않습니다. `agent365_tools_enabled: false`로 추가 조회를 끌 수 있습니다.

MCP·Skill은 검증된 `catalog_tool_types`만 보존합니다. 연결·원본 ID 중복은 SHA256 기준이며, 목록 제외를 원본 삭제로 해석하지 않습니다. 대상은 사용자·그룹별 개수만 저장하고 알 수 없는 유형은 `null`입니다.

연결 상태 화면 증적은 `--agent365-connections-file <파일.json>`으로 collect/package에 첨부합니다(package는 `--tenant-id` 필요). 봉투는 `schema_version=1`, `source_type=official_admin_portal_read`, `approved/tenant_verified=true`, `tenant_id`, `observed_at`, `source_url=https://admin.cloud.microsoft/#/agents/all/connected-platforms`, `connections`입니다. 각 연결은 `platform`, `connection_label_sha256`, `status`(Healthy/Success/Failed/Unknown), 선택 `last_sync_at`, `synchronized_count`, `observability_enabled`, `error_present`를 담습니다. 최근 24시간·중복·미래 시각을 검증하며 수집 방식은 E입니다. 화면의 연결 이름을 Graph 연결 ID와 추정 매칭하지 않습니다.

`platform=AmazonBedrock`(P5)·`SnowflakeAI`(P6)는 Graph 패키지 목록·상세 `v1.0`으로만 읽습니다. 원본 플랫폼 API는 평가 증거로 사용하지 않습니다.

| 항목 | 평가 조건 |
| --- | --- |
| DS-SY-04 (Bedrock) | 연결 정의 `SourceIds.mac.modelInfo`의 검증된 모델 식별자 |
| DS-SY-05 | `availableTo`·`isBlocked`의 명시적 구성 기록 |
| DS-SY-07 (Snowflake) | 연결 정의 `AgentEndpoints[].EndpointUrl`의 유효 HTTPS·인증정보 부재. endpoint 수 기준, URL 원문 미저장 |
| BI-SY-12 | 패키지 `version` 기록. 원본 코드·모델·배포 버전과 대사하지 않음 |
| OE-SY-16 | 검증된 등록부 소유자 수 > 0. 원본 IAM 역할·Snowflake 소유 역할로 추론하지 않음 |
| DP-SY-15 | 연결 정의 `SourceAgentId`·`SourceIds.ConnectionId`의 등록 패키지 연결 기록. 원본 ID·연결 ID는 SHA256만 저장. Entra 청사진·실행 인증 연결 아님 |
| OE-SY-22 (Bedrock) | 연결 정의 `SourceIds.mac.region`의 명시적 리전. 로그 보존·모델 실제 처리 지역 아님 |
| API 필드 미지원 | 매트릭스에는 `해당 없음`으로 표시하되 계산 제외·미지원 사유는 비고·근거·JSON에 유지. 조회·확인 실패는 `X`이며 0·충족으로 바꾸지 않음 |

Graph v1.0 상세의 `elementDetails[].elements[].definition`은 JSON 문자열입니다([요소 정의](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/admin-settings/package/resources/packageelement)). `AgentMetadatas`·`SourceIds`·`mac.*`는 2026-11-26 실제 응답에서 확인했으나 공개된 안정 내부 스키마는 없습니다. `connected_definition_v1`로 허용 필드만 검증하며 정의 변경·중복·누락은 `null`과 사유로 기록합니다. 지침·설명·사용자·계정 ID·연결 문자열·URL 원문은 저장하지 않습니다. Snowflake의 `mac.region`·`AgentLocation`은 빈 값이므로 지역을 URL에서 추정하지 않습니다.

활동 0을 실행 0회·90일 미사용으로 해석하지 않습니다. 연결은 [이기종 설정](connected-platforms.md)을 따릅니다.

## 관리자 읽기 내보내기

진단 SP와 분리된 승인 사용자로 읽습니다. 역할·정책 변경 없이 환경·역할 건수·DLP 적용 범위만 저장합니다. **별도 신원이지 수동 파일 작성이라는 뜻은 아닙니다.** 데모 원클릭은 환경·DLP를 자동 내보내며 일반 `collect`에는 파일을 전달합니다.

| 원천 | 보관 값·한계 |
| --- | --- |
| 환경 GET `2024-10-01` | Azure CLI 관리자 로그인. id·displayName·type·protectionLevel·azureRegion만 저장. 누락은 `null`, 전체 페이지 확인 |
| PowerShell 모듈 `Microsoft.PowerApps.Administration.PowerShell` 2.0.220 이상 | `Get-AdminPowerAppEnvironmentRoleAssignment`·`Get-AdminDlpPolicy`. 비 Dataverse 환경의 역할 할당 건수와 DLP 환경 적용 범위만 저장 |
| Dataverse 역할 | `scripts/export_dataverse_roles.py`. 사용 설정된 대화형 사용자 중 System Administrator·Environment Maker 건수(이름 미내보내기). 두 원천이 있으면 명령 결과 우선 |
| DLP V2 API | `GET https://api.bap.microsoft.com/providers/PowerPlatform.Governance/v1/policies?$top=50`, 토큰 audience `https://service.powerapps.com/`. `environmentType`·`environments[].name`만 저장. 성공한 빈 목록은 정책 0건, 403·미완료 페이지는 `null`과 사유 |
| 관리 센터 화면 | `source_type=official_admin_portal_read`. 필터 없는 전체 목록을 확인한 승인 관리자만 내보내며 로딩·실패 화면을 빈 목록으로 기록하지 않음. 확인하지 않은 환경 역할은 `null` |
| 공통 | 승인된 현재 사용자만 사용. 모듈 부재는 `feature_unavailable`, 조회 실패는 건수 `null`. 테넌트·시간·명령·모듈 버전을 검증하고 마스킹 증적과 SHA256 보관 |


승인된 PowerShell 저장소 이름을 명시합니다. 다른 저장소로 자동 전환하거나 기존 저장소를 등록·덮어쓰지 않습니다.

```powershell
$repository = "<승인된-저장소명>"
Find-Module Microsoft.PowerApps.Administration.PowerShell -MinimumVersion 2.0.220 -Repository $repository -Verbose
Save-Module Microsoft.PowerApps.Administration.PowerShell -RequiredVersion 2.0.220 -Repository $repository -Path .easm-agent\tools\psmodules -Verbose
$env:PSModulePath = (Resolve-Path .easm-agent\tools\psmodules).Path + [IO.Path]::PathSeparator + $env:PSModulePath
Import-Module Microsoft.PowerApps.Administration.PowerShell -MinimumVersion 2.0.220 -Verbose
```

모듈·실행 정책이 차단하면 승인 환경 또는 실제 화면 증적을 사용합니다. `ExecutionPolicy Bypass`·인증서 검증 해제는 금지합니다. Power Platform 모듈의 장치 코드 미지원 환경은 승인 데스크톱 JSON을 사용합니다.

```powershell
python scripts\export_admin_environments.py --tenant-id <테넌트-ID> --output .easm-agent\admin-exports\environments.json
python scripts\export_dataverse_roles.py --tenant-id <테넌트-ID> --output .easm-agent\admin-exports\dataverse-roles.json
.\scripts\export_admin_evidence.ps1 -TenantId <테넌트-ID> -Service PowerPlatform -OutputPath .easm-agent\admin-exports\powerplatform.json -Login Browser
easm-agent package --output-dir output\<실행폴더> --tenant-id <테넌트-ID> `
  --admin-evidence-file .easm-agent\admin-exports\environments.json `
  --admin-evidence-file .easm-agent\admin-exports\powerplatform.json --reassess
```

`package` 전 수동 입력본을 보관합니다. 원래 수집 시각과 관리자 조회 시각은 별도로 유지하며 실제 환경 식별자는 공개 문서에 기록하지 않습니다.

## 추가 보고서 증적

보고서 전용 지표(27~39)는 26개 API 등급에 합산하지 않으며 명칭·지표·기간은 `criteria.yaml`의 `report_items`·`report_options`가 기준입니다. 값이 없으면 `null`과 사유이고 PPT에는 '확인 중'으로 표시합니다.

| 코드 | 처리 |
| --- | --- |
| DM-SY-27·DP-SY-28 | 승인 워크플로·조직 등록부의 명시적 ID·시간을 승인 파일로 대사. 배포 승인·서비스 카탈로그로 대체하지 않음 |
| BI-SY-29 | 동일 버전·완료 시각·배포 시각 대사. 평가 생성 시각으로 대체하지 않음 |
| OE-SY-30 | `GET /beta/identity/conditionalAccess/policies`(`Policy.Read.All`, 별도 관리자 읽기). `enabled`와 명시적 `includeAgentIdServicePrincipals` ID만 대사하고 `All`·속성 필터는 해석하지 않으며 보고 전용은 집행으로 세지 않음 |
| OE-SY-31 | `Get-UnifiedAuditLogRetentionPolicy`의 사용자 지정 정책 enum(3/6/9/12/120개월). 실제 보존이 아님 |
| OT-SY-32 | Agent 단위 전체 관측 구간·30/90일 호출 수. 짧은 로그 구간으로 미사용을 단정하지 않음 |
| OT-SY-33 | 승인된 발견·심각도·조치 상태 내보내기. Defender 플랜·경보 종료와 다름 |
| OT-SY-34 | `--report-cost-history`로 현재 발견된 Azure AI 리소스의 기간별 비용. 삭제 리소스·M365 청구 제외 |
| DP-SY-35·DS-SY-36·OE-SY-37 | Copilot 인벤토리의 게시 시각·인증 방식·소유자 존재. 독립 보안 평가가 아님 |
| DP-SY-38 | 카탈로그 `requestType=publish`의 승인 상태. Agent 생성 업무 승인이 아님 |
| OE-SY-39 | 승인된 인사 대사 결과의 Agent ID·nullable bool만 사용. 계정 비활성은 퇴사 증거가 아님 |

### 승인된 추가 증적 파일

| 필드 | 계약 |
| --- | --- |
| 봉투 | `schema_version=1`, `source_type=approved_report_evidence`, `approved=true`, `tenant_id`, `tenant_verified`, `data_mode=live`, `exported_at`, `datasets` |
| 데이터셋 | 코드·`kind`·`scope`·`source_kind`·`source_ref`·`observed_at`·`complete`·`population_complete`·`reason`·`records`. 시계열은 시간대 있는 `period_start/end` 필요 |
| 개인정보 | `subject`는 기술 ID. 이름·인사 원문·대화·민감 정보 본문 금지 |
| 신뢰 | 승인 표시·테넌트 일치·최근 24시간·스키마·시간 검증 후 마스킹 저장. 중복 코드·ID·미래 시각 거부. 해시는 원천 서명이 아님 |
| 실패 | 미완료는 `complete=false`와 표준 사유. 미확인·빈 분모·전체 모집단 미확인은 `null` |

```powershell
python scripts\export_report_evidence.py --schema > report-evidence-schema.json
python scripts\export_report_evidence.py --conditional-access --approved --tenant-id "<테넌트 ID>" --output conditional-access.json
easm-agent collect --setup-file .easm-agent\setup.json --report-cost-history --report-evidence-file conditional-access.json
```

수집할 수 없는 업무·인사·과거 이력을 배포 영수증으로 만들어 채우지 않습니다. 새 증적 첨부에는 `package --reassess`와 명시적 테넌트가 필요합니다.

## Excel·PPT 계약

월별 표는 **생성월·현재 구성 상태**이며 과거 승인·게시·실행 이력이 아닙니다. 비용은 동일 사용일·리소스·통화·금액과 현재 인벤토리의 단일 매칭을 대조합니다. 과거 귀속·이기종 비용은 추정하지 않습니다.

| 구분 | 계약 |
| --- | --- |
| 출력 | 실행별 `output/<실행시각-UTC>/`에 Excel·PPT·JSON. 실제 수집 시각은 `collection.collected_at` |
| Excel 템플릿 | `assessment-result-template.xlsx`의 통합 14개 시트·폰트·크기·수동 입력을 유지하고 뒤에 근거·Raw 4개 시트 추가. 과거 `6. 수집 결과` 입력도 읽음 |
| 원천데이터 | `2_SE 원천데이터` F열에 항목별 측정값. E열은 `criteria.yaml`의 `numerator`·`denominator` 문구를 사용. 추출 일시는 `yyyy-mm-dd hh:mm:ss KST`, 추출자는 `EASM 자동화 모듈`. 숨김 L열은 UTC 시각, M/N열은 기계 판독용 단위·통화(KST·한글 단위가 Excel 단독 PPT 변환을 바꾸지 않음) |
| 판정 | `3_SE 판정`은 수집 당시 등급과 기준 사본을 반영. 숨김 U:Y열은 저장 API 등급·충족률·상태·사유·조치이며 헤드리스 PPT 생성이 읽음 |
| 수동 입력 | 인터뷰 54문항·문서·인용을 보존하며 `--interview-workbook`으로 원본 지정. API가 확인한 결과가 아님 |
| 집계 | 인터뷰 54개·SY 26개. 증적 상한(문서 없음 최대 2점·시스템 증적 없음 최대 3점)을 적용하고 빈칸·N/A는 제외. 환경·리소스·Agent ID·금액 분모를 전사 Agent 커버리지로 합산하지 않음 |
| 괴리 보정 | 인터뷰 영역 평균 - SY 평균 >= 1.5이면 SY 평균 + 1.0으로 보정(소수 첫째 자리 반올림). 미확보를 0으로 보간하지 않음 |
| 수집 방식 표기 | A는 공식 API 읽기(승인된 위임 사용자 내보내기 포함), E는 실제 관리 화면·수동 증적. 파일 전달 여부가 아닌 실제 원천으로 구분 |
| 플랫폼 분해 | Power Platform 항목은 P1·P2 공통 측정, Copilot 확장은 해당 Agent의 판정만, Graph Agent ID는 실제 귀속 기준. Azure 수를 Copilot에 복제하지 않으며 P4~P7 미수집을 제품 전체 미지원으로 단정하지 않음 |
| 수집 실패 | 수집 시작의 인증·접근 실패는 표준 사유로 N/A 26개 Excel·PPT를 만들고 종료 코드 2. 설정 오류·템플릿 손상·출력 권한 오류는 명시적으로 실패 |
| 템플릿 갱신 | `python -m scripts.merge_assessment --source <검토할-xlsx> --output <다른-경로.xlsx>`. 원본 덮어쓰기 금지 |
| 색상 | 같은 표의 입력·참조 열은 빈 셀·수식도 노란 바탕·파란 글자, 합계·판정 조건부 서식 유지, 교대 행 채우기 없음 |

### PPT 작성 지침

작성 코드는 `report_pptx.py`·`report_story.py`·`report_narrative.py`·`report_terms.py`입니다.

| 구분 | 지침 |
| --- | --- |
| 템플릿 | 27장 [원본](assessment-report-template.pptx)의 배경·마스터·테마·미디어를 보존하고 텍스트·표·동적 막대만 갱신. 슬라이드·노트 XML 외 ZIP 부품은 템플릿과 바이트 동일 |
| 숫자 | raw JSON과 Excel 점수에서 계산하며 하드코딩하지 않음. 비용 분자·분모가 반올림으로 같아 보여도 충족률을 함께 표시 |
| 고정 문구 | 제목·소제목·표 머리글·차트 라벨은 템플릿 원문 유지. 수준은 `L1`~`L5`, `L2.9`, `목표 L3` 형식 |
| 비즈니스 페이지 | 사업 목표·VOC·성과는 원문 참고 자료이며 API 검증 결과가 아님. 개선 범위·기간은 제안 |
| 값이 없을 때 | `N/A`·사유 코드 대신 '확인 중'. 0점·L1로 대체하지 않고 평균에서 제외하며 판정 분포에 '확인 중' 칸을 둠 |
| 지표 | 원천 없는 사실은 추정하지 않음. 보조 지표의 범위를 각주로 명시. 월 경계는 KST |
| 라벨 | 지표의 실제 의미를 따름(예: 역할 할당 환경 비율을 '제작 권한 통제'로 쓰지 않음). 목표(80%) 초과는 '목표 충족, 나머지 보완 필요'. 같은 데이터는 한 판정 함수로 2장·3장에 동일하게 표시 |

## 고객 셋업·정리 계약

실행 명령·화면은 [README Step 1~6](../README.md#진행-순서)를 따릅니다. 실행하지 않은 인증·배포·삭제는 완료로 표시하지 않습니다.

| 구분 | 계약 |
| --- | --- |
| 전달물 | [고객 ZIP](downloads/customer-setup.zip)(`setup.sh`·`setup_account.py`·`foundry-reader.json`·`cleanup_account.py`)과 별도 전달하는 공개 인증서. 설정·개인키·수집기는 제외. 갱신은 `python -m scripts.package_customer_setup` |
| 고객 실행 | Python 3.11 이상·Azure CLI·Bash만 필요하며 완료한 `setup.json`만 반환. 관리자 인증 정보는 전달하지 않고 개인키는 MS가 보관. `verify`는 MS 저장소에서만 실행 |
| `apply` | Client ID로 SP를 조회해 앱 이름·Client ID·SP 개체 ID를 검증. 실패 시 쓰기 전 중단하며 이름 대체·새 SP 생성 금지 |
| Azure·Foundry·Graph 권한 | README Step 4의 표와 동일. Foundry 역할은 승인 구독에 할당해 기존·이후 프로젝트에 상속(`--foundry-project-scopes`로 제한 가능). Owner·Contributor·Foundry User 부여 금지 |
| Graph 동의 | `requiredResourceAccess`와 appRoleAssignments를 일치시키되 기존 타 API 권한은 보존. 활성 Privileged Role Administrator 또는 Global Administrator 필요(Global Reader 불가). PIM 활성화 후 `bash setup.sh login --login-resource graph`로 재실행. 오류 본문·토큰은 출력하지 않음 |
| 인증서 경로 | `.easm-agent/certificate-path` 재사용. 기록이 없으면 `auth-*/diagnostic.pem`이 정확히 하나일 때만 선택하며 개인키 내용은 읽지 않음 |
| 사전 점검 | 대상 없음·endpoint 미지정은 `NOT_CHECKED/not_found`(종료 0·수집 계속). `DENIED`·`ERROR`·`FEATURE_UNAVAILABLE`은 종료 2 |
| `cleanup-plan` | 삭제 없이 대상 조회. setup.json의 테넌트·Client ID·SP 개체 ID·진단 전용 앱 이름과 Single tenant 유형 검증 |
| `cleanup-apply` | 승인 구독의 해당 SP 역할 할당을 먼저 회수하고 앱·SP 부재를 재조회한 뒤 일치하는 진단 사용자 지정 역할만 정리. 다른 주체의 활성·PIM 적격 할당이 있거나 조회가 실패하면 보존. 삭제 후 동일 역할 ID 부재를 최대 6회 확인 |
| 로컬·별도 승인 | 인증서·개인키·암호 환경변수·setup.json·CLI 세션·공유 보고서는 승인된 보관 정책에 따라 정리. 스크립트는 영구 삭제를 하지 않으며 삭제된 앱은 30일간 복원될 수 있어 완전 폐기는 고객 승인 후 별도 수행 |
