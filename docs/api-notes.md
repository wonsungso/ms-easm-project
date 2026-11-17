# API·평가 기준 참고

| 찾을 내용 | 위치 |
| --- | --- |
| 실행·권한 설정·정리 | [README](../README.md) |
| 항목별 설명·확인 화면 | [점검 항목 상세](checklist.md) |
| 지표·분모·증거·한계·등급 규칙 | [criteria.yaml](../config/criteria.yaml)의 `grading_profile: api_configuration_v1` |
| 읽기 API·버전·공식 근거 | [공식 API 계약](#공식-api와-읽기-계약) |
| 별도 관리자 증적 | [내보내기 절차](#관리자-읽기-내보내기) |
| 테스트 환경 배포 | [개발용 데모](../demo/README.md) |

승인된 과거 원본은 Git 제외 로컬 `source-materials/`에 보관하며 실행에 필요하지 않습니다. 과거 원문 Level·구성 L2 기본등급은 현재 평가에 사용하지 않습니다.

## 범위 원칙

용어는 MS Learn의 [소유자·스폰서·관리자](https://learn.microsoft.com/ko-kr/entra/agent-id/agent-owners-sponsors-managers), 에이전트 ID 청사진, [민감도 레이블](https://learn.microsoft.com/ko-kr/purview/sensitivity-labels)을 사용합니다. API 키·실제 메뉴·리소스 이름은 유지합니다.

| 구분 | 범위·처리 |
| --- | --- |
| 수집·평가 | Microsoft Foundry, Azure 자체 호스팅 Agent, Azure Monitor·Log Analytics, 비용·보안 권고, Defender for Cloud 플랜, Entra Agent ID, Agent 365 등록부, Power Platform 관리자 읽기의 31개 항목 |
| Entra 필수 조회 | DS-SY-05, DP-SY-19, OE-SY-20~21. 생략 옵션 없이 권한 부족은 항목을 유지하고 `null`과 사유 기록 |
| 등록부 5개 | DM-SY-01·03, DP-SY-17~18, OT-SY-27. Agent 365 등록부 API와 라이선스가 필요하며 조회 실패는 `null`과 사유로 유지 |
| 관리자 읽기 3개 | DM-SY-02·DS-SY-04·BI-SY-10. 승인된 관리자가 별도 실행하는 읽기 내보내기 증적을 사용하며 진단 SP 권한은 확대하지 않음 |
| 범위 구분 | Azure 인벤토리는 Agent Registry·인사 대사를 대체하지 않음 |
| 자체 Agent 탐지 | 승인 구독의 App Service·Container Apps·AKS. 기본 LangChain 조건에 사용자 태그 OR 조건 추가. 태그만 일치하면 `custom` 후보이며 실제 실행 증거는 아님. [설정 예시](../README.md#자체-agent-탐지-태그) |
| 승인 경계 | 지정 테넌트의 접근 가능한 구독을 기본 열거하고 CLI·설정의 승인 범위를 적용. 외부 workspace·청구 범위 접근을 자동 확대하지 않음 |
| 실행 신원 | 진단 SP의 DefaultAzureCredential. Reader 중심 GET 및 Resource Graph·비용·로그의 읽기 query POST만 허용 |
| 보안 권고 범위 | 현재 발견한 AI 리소스·하위 리소스로 Resource Graph 요청과 응답을 제한. 삭제·무관 리소스 권고는 증적에서 제외 |
| 관리자 예외 | `scripts/setup.sh`, `setup_account.py`, 정리 스크립트와 demo만 승인된 배포·역할·일회성 인증 준비 수행. 수집기에서 import 금지 |
| 결과 번호 | `assessment_revision: 5`는 01~31 순번. Demand 01~03, Design 04~09, Build 10~16, Deploy 17~19, Operate 20~26, Optimize 27~31 |
| 호환성 | 이전 revision 4는 항목·점수·증거 귀속을 보존해 한 번 변환. 더 오래된 결과는 위험 Agent·Red team 제거와 구 번호 변환을 먼저 수행 |
| 제외 API | Red team·조건부 접근·위험 Agent 진단 제외. 기존 Graph 추가 권한은 관리자가 회수 가능 |

## 판정 근거와 재현성

| 결과 위치 | 확인할 내용 |
| --- | --- |
| `findings[].evidence_refs` | 해당 항목의 조회·계산에 직접 사용한 증적. 모든 항목에 전체 증적을 공통 연결하지 않음 |
| `findings[].measurement` | 분자·분모, 개수/금액 구분, 통화, 계산 완료 여부와 보류 사유. 실패·미확인·빈 분모는 계산값 `null` 유지 |
| `measurement.targets[]` | 대상 식별자, 실제 확인 값, 충족·미충족·미확인·계산 제외 상태, 계산 기여값과 증적 참조. 부분 관측값은 종합 점수가 아님 |
| `collection.evidence_sources` | API 요청 주소와 증적 참조의 연결. 페이지가 여러 개인 조회도 같은 원천의 증적을 찾아 연결 |
| `provenance.references` | 연결된 증적은 `evidence:<SHA256>`로 표시. 로컬 절대 경로 대신 참조 키의 SHA256을 보관해 재패키징 시 연결 유지 |
| `collection.assessment_provenance` | 평가 시각, 마스킹된 유효 평가 기준·태그 규약의 사본과 SHA256, 수집기 패키지 버전·Python 소스 묶음의 SHA256 |
| Excel 6번 상단 | 등급 산정·판정 보류·결과 없음 및 조회 이슈 요약. L5는 API 구성·기록 조건 100% 충족이며 조직 전체 성숙도·정책 실효성의 증명이 아님 |
| Excel 6번 경계선 | 진단 영역이 바뀌는 행의 G~N열 위쪽 테두리를 B열의 진한 경계선에 맞춤. 다른 테두리·값·점수는 유지 |
| Excel 7번 | 항목 요약·전체 리소스 목록·대상별 판정·평가 출처. 비용은 건수가 아닌 금액·통화로 확인 |

| 재현성 규칙 | 처리 |
| --- | --- |
| 해시 | 기준 JSON은 UTF-8·키 정렬·공백 없이 직렬화한 SHA256. 소스는 Python 파일별 SHA256 목록을 같은 방식으로 해시. 원천 서명·배포 승인은 아님 |
| 과거 결과 | 당시 사본이 없으면 현재 기준으로 채우지 않음 |
| `package` | 저장 판정·기준 사본 유지. 새 기준·관리자 증적의 판정 반영은 `--reassess` 필요 |
| 재평가 | 원래 수집 시각 유지. `origin=saved_snapshot_reassessment`·재평가 시각·원본 데이터 SHA256 기록. 당시 수집기 버전의 검증은 아님 |
| 불완전한 분모 | 일부 대상이 충족해도 전체 조회 미완료이면 종합 계산값·점수 보류 |

## 심사기준 검토와 점수 반영 (2026-11-05)

충족률은 전체 분모 중 API 증거가 조건을 충족한 비율입니다. **비용만 건수가 아닌 금액 기준**입니다.

| API 충족률 | Level | 점수 |
| --- | --- | --- |
| 0% | L1 | 1 |
| 0% 초과~80% 미만 | L2 | 2 |
| 80% 이상~90% 미만 | L3 | 3 |
| 90% 이상~100% 미만 | L4 | 4 |
| 100% | L5 | 5 |

| 판정 계약 | 적용 |
| --- | --- |
| 완전성 | 전체 대상 인벤토리·페이지·항목별 관련 조회와 필수 필드를 확인한 뒤 계산. 일부 성공한 응답만으로 전체 비율을 만들지 않음 |
| L1 | 유효한 양수 분모에서 확인된 충족률 0%에만 적용 |
| 판정 불가 | 권한 거부·기능 미제공·라이선스 부족·조회 실패·필수 필드 미확인·빈 분모는 `null`과 `permission_denied/feature_unavailable/license_missing/not_found/error` 사유. L1·0%로 대체하지 않음 |
| 명시적 부재 | 조회가 완료되고 필드가 명시적으로 비어 있거나 조건을 미충족한 경우와 조회 자체가 실패한 경우를 구분 |
| 고객 입력 | `policy_facts`, 외부 승인, `major_type_blueprints_defined`, 허용 모델·내부 기준 등 과거 Settings 필드는 기존 로컬 설정 로딩 호환용이며 현재 등급에 사용하지 않음 |
| 해석 한계 | L4/L5도 아래 API 구성·기록의 비율을 뜻함. 정책의 승인·실효성·자동화 동작·개선 효과를 설정만으로 추론하지 않음 |
| 기준 변경 | 지표·임계값·기간은 `criteria.yaml`, 수집 기술 설정은 선택 `custom-config.yaml`. `--criteria`로 별도 기준 지정. 설치본 기본 기준도 패키지에 포함 |
| 범위 | `partial` 결과는 명시된 Azure 부분 범위의 지표이며 조직 전체 원 통제 충족을 의미하지 않음 |

### 31개 API 지표

| 코드·현재 명칭 | 분모 | 충족 API 증거 | 해석 한계 |
| --- | --- | --- | --- |
| DM-SY-01 Agent 거버넌스 분류 | Agent 365 등록 패키지 수 | `governanceMetadata`가 `Unmanaged`가 아닌 값 | 포털의 제작 허용 사용자·그룹 설정 아님. 분류 값 미확인은 null |
| DM-SY-02 Power Platform 환경 역할 할당 | 관리자에게 보이는 환경 수 | 환경별 역할 할당 건수 1 이상(`Get-AdminPowerAppEnvironmentRoleAssignment`) | 비 Dataverse 환경만 반환되어 과소 집계 가능. 고유 제작자 수·전체 유효 권한 아님 |
| DM-SY-03 신규 Agent 승인 요청 기록 | 최근 183일 내 생성된 패키지 수 | `createdDateTime`이 기간 내이고 `requestStatus=approved` | 패키지 생성일이며 실제 Agent 생성일 아님. 상태가 null이면 승인 기록 없음으로 계산하고 생성일 미확인은 null |
| DS-SY-04 데이터 정책 환경 적용 | 관리자에게 보이는 환경 수 | DLP 정책 `FilterType`·`Environments`로 환경이 범위에 포함(전체·포함·제외 해석) | 커넥터 분류·차단 효과 아님. 정책이 없으면 0% |
| BI-SY-10 관리형 환경 보호 수준 | 관리자에게 보이는 환경 수 | 환경 `protectionLevel=Standard` | `Standard`=관리형 환경은 필드 값에 근거한 해석. 환경 분리 실효성 아님 |
| DP-SY-17 등록 패키지 소유자·배포 기록 | Agent 365 등록 패키지 수 | `owners` 1명 이상과 `deployedTo`·`isBlocked` 기록 | 소유자 수만 사용(이름 미저장). 미등록 자산·승인 목록 대사 아님 |
| DP-SY-18 패키지 공유·배포 범위 제한 | Agent 365 등록 패키지 수 | `availableTo≠allowedForAll`이고 `deployedTo≠acquiredForAll` | 테넌트 설치 정책 아님. 값 미확인은 null |
| OT-SY-27 Azure Agent의 등록부 등록 | Azure에서 발견한 Agent 수 | Agent의 Entra Agent ID가 등록부 `agentIdentityId`에 존재 | Shadow AI 탐지 리포트 아님. 등록부에 없다는 이유만으로 미승인으로 단정하지 않음 |
| DS-SY-05 Agent ID의 Blueprint 연결 | Graph Agent ID 수 | `applications/microsoft.graph.agentIdentityBlueprint`와 `servicePrincipals/microsoft.graph.agentIdentity`의 `agentIdentityBlueprintId` 대조 | Blueprint 조직 표준 승인·업무 유형 분류 아님 |
| DS-SY-06 모델 배포 버전·업데이트 구성 | 모델 배포 수 | `model.name·version·format`과 기준에 정의된 `versionUpgradeOption` 모두 존재 | 허용 모델 대조·퇴역 대응 완료 아님 |
| DS-SY-07 AI 리소스 인바운드 경계 구성 | AI 계정·자체 Agent 호스트 수 | AI 계정의 `publicNetworkAccess`와 Approved `privateEndpointConnections`, 호스트의 기본 거부 접근 제한 또는 비공개 ingress | 송신 경계·실제 차단 효과 아님. HTTPS·VNet 통합만으로 충족하지 않음 |
| DS-SY-08 MCP 도구 필수 승인 모드 | MCP 도구 선언 수 | 최신 Agent 버전 `definition.tools`의 MCP `require_approval=always`만 충족 | `never`·명시적 객체형 `custom`은 미충족, 값 미확인은 null. 함수·내장 도구 제외. 런타임 승인 우회 방지 검증 아님 |
| DS-SY-09 외부 도구 HTTPS 연결 구성 | 명시적 외부 도구 URL 수 | `server_url·url`의 HTTPS scheme·유효 hostname·userinfo 부재 | 업무 승인·상대 서버 신뢰·인증 성공 아님. 경로·쿼리·인증값 미저장 |
| BI-SY-11 Foundry 프로젝트 평가 실행 이력 | Foundry 프로젝트 수 | `/openai/v1/evals`와 `/evals/{id}/runs`에서 `completed` 또는 `succeeded` 실행 보유 | 프로젝트 이력이며 배포 전 평가·Agent 버전별 품질 통과율 아님 |
| BI-SY-12 AI 리소스 보안 권고 상태 | 적용 가능한 AI 보안 권고 수 | `SecurityResources` assessments의 `resourceDetails.Id` 연결과 `status.code=Healthy`, `NotApplicable` 제외 | 권고 없음은 100% 아님. 구독 보안 점수·권고 나이·조치 SLA 채점 안 함 |
| BI-SY-13 콘텐츠 필터 정책 연결 | 모델 배포 수 | 배포 `raiPolicyName`으로 연결된 실제 `accounts/raiPolicies`를 식별하고 `contentFilters.enabled` 확인 | 필터 값 미확인은 null. 실제 차단 효과·강도 승인 아님. 정책명만으로 충족하지 않음 |
| BI-SY-14 Agent 버전·호스트 런타임 식별 | Foundry Agent·자체 호스트 수 | Agent `version`, `sites/config/web.linuxFxVersion`, Container Apps 이미지 sha256 다이제스트 | 소스·빌드 출처·운영 배포 승인·롤백 기록 아님 |
| BI-SY-15 Agent 책임·환경·비용 메타데이터 | Azure Agent 수 | 같은 Agent의 태그 또는 API metadata에 owner·sponsor·env·cost-center 모두 존재 | 값의 업무 승인·인사 상태 아님 |
| BI-SY-16 AI 리소스 정책 평가 준수 | 정책 평가가 있는 AI 관련 리소스 수 | `PolicyResources` policyStates를 리소스별 대조해 모든 평가가 `Compliant` | `Exempt·Unknown`·평가 없음은 준수 아님. 자동 교정 효과 아님 |
| DP-SY-19 Azure Agent의 Entra Blueprint 귀속 | Azure Agent 수 | Entra Agent ID·Blueprint 전체 조회 완료 후 Blueprint tags의 subscriptionId·accountName·projectName·agentName을 Foundry Agent와 정확 대조하고 실제 Agent ID의 해당 Blueprint 참조 확인 | Blueprint 태그만으로 충족하지 않으며 LangChain 관리 ID를 Entra Agent ID로 대신 간주하지 않음 |
| OE-SY-20 Agent ID 소유자·스폰서 연결 | Graph Agent ID 수 | 실제 `owners` 수 > 0 및 `sponsors` 수 > 0 | 기본 Graph 읽기 권한의 사용자 속성 제한 때문에 accountEnabled는 조건에서 제외. 계정 활성 상태·퇴사자 판정·인사 대사 아님. 이름·UPN 미저장 |
| OE-SY-21 Agent ID 앱 역할 읽기 범위 | Graph Agent ID 수 | `appRoleAssignments`와 대상 SP의 `appRoles.value`를 해석해 기준의 쓰기·전체제어 패턴 앱 역할 없음 | ARM·위임·앱 내부 권한 제외 |
| OE-SY-22 Agent 리소스 실행 로그 연결 | AI 계정·자체 Agent 호스트 수 | `diagnosticSettings.logs.enabled`와 `workspaceId` 연결 | 구독 공통 Activity Log 제외. 이벤트 유입·테이블 유효 보존기간 아님 |
| OE-SY-23 관리 ID·키 인증·직접 ARM 역할 구성 | AI 계정·자체 Agent 호스트 수 | `identity.principalId·type` 존재, 동일 구독의 광범위 직접 역할 없음, AI 계정 `disableLocalAuth=true` | 타 구독·상속·데이터 평면 역할과 실제 인증 사용 제외 |
| OE-SY-24 AI 리소스 활성 경보 범위 | AI 계정·자체 Agent 호스트 수 | `metricAlerts·scheduledQueryRules·activityLogAlerts`의 enabled·scopes를 실제 AI 리소스 ID에 대조 | 경보 발생·SLO 충족·trace 유입 아님 |
| OE-SY-25 AI 경보의 작업 그룹·수신자 연결 | AI 대상 경보 수 | 활성 경보의 actionGroupId·actionGroups에 존재하는 작업 그룹과 활성 email·SMS·webhook·armRole·Function·LogicApp·ITSM receivers 연결 | 실제 전달 성공·온콜 대응 시간·복구 시험 아님. 주소·이름 미저장 |
| OE-SY-26 리소스 지역·workspace 보존 구성 | AI 계정·자체 Agent 호스트 수 | `resources.location` 식별·활성 로그의 연결 workspace `retentionInDays` 기준 충족, 기본 90일 | 실제 처리 지역·테이블별 유효 보존·법적 삭제 아님 |
| OT-SY-28 AI 리소스 사용량 관측 범위 | AI 계정·자체 Agent 호스트 수 | `metricDefinitions`와 `metrics.timeseries.data`에 기간 내 숫자 표본, 기본 30일 | 숫자 0도 관측됨. Agent별 사용자 수·90일 미사용 여부 아님 |
| OT-SY-29 AI 비용의 단일 Agent 귀속 | 동일 통화의 양수 AI 비용 금액 | Daily query의 ResourceId·UsageDate·Cost·Currency와 Agent·모델·호스트·플랜 ID 대조. 일자 존재·단일 Agent 귀속 금액, 기본 30일 | 공유 비용 중복 배분 금지. 통화 혼재·음수 조정·분모 0은 산출하지 않음 |
| OT-SY-30 AI 민감 데이터 노출 점검 구성 | 승인 구독 수 | `Microsoft.Security/pricings`(2024-01-01)의 `AI` 플랜 `pricingTier=Standard`, `CloudPosture` 플랜 `Standard`와 `SensitiveDataDiscovery` 확장 `isEnabled=True`를 모두 충족. `AIPromptEvidence`·`AIModelScanner` 확장은 상태만 기록 | 플랜·확장 구성이며 실제 경보 발생·민감 데이터 노출·조치 완료 아님. 구독 안 모든 AI 리소스 적용 범위 미확인. 필드 누락은 `null` |
| OT-SY-31 구독 예산·실제·예측 경보 구성 | 승인 구독 수 | 현재 유효한 양수·무필터 `Cost` 예산과 활성 Actual·Forecasted 임계값 경보·수신자 존재 | Agent별 예산·실제 전달 성공·통보 후 자동 조치 아님 |

- DS-SY-06의 기본 업데이트 옵션은 `NoAutoUpgrade`, `OnceNewDefaultVersionAvailable`, `OnceCurrentVersionExpired`입니다. 어느 옵션도 조직의 모델 승인이나 퇴역 대응을 보장하지 않습니다.
- OE-SY-21의 기본 패턴은 `*.ReadWrite.All`, `*.Write.All`, `*FullControl*`이며 `criteria.yaml`에서 관리합니다. 매칭되지 않는 역할을 모든 권한에 대한 최소 권한 인증으로 해석하지 않습니다.
- OE-SY-26의 기본 보존 기준은 `workspace_retention_target_days: 90`, OT-SY-28은 `usage_window_days: 30`, OT-SY-29는 `cost_window_days: 30`입니다. workspace 설정값은 테이블별 유효 보존기간이 아닙니다.
- OT-SY-31은 `amount·category·timePeriod·filter`, 활성 notifications의 `thresholdType·threshold`와 수신자 존재를 함께 확인합니다. 만료·향후 예산, 필터 예산 또는 예측 경보만 있는 예산을 구독 전체 충족으로 간주하지 않습니다.
- OT-SY-30은 진단 SP의 Security Reader로 `Microsoft.Security/pricings`를 읽습니다. 응답에 AI 또는 CloudPosture 플랜이 없거나 필드를 확인하지 못한 구독이 있으면 `null`과 사유를 유지하고 L1로 대체하지 않습니다. 공식 근거: [AI 서비스 위협 방지 활성화](https://learn.microsoft.com/en-us/azure/defender-for-cloud/ai-onboarding), [AI 보안 상태 관리](https://learn.microsoft.com/en-us/azure/defender-for-cloud/ai-security-posture), [Pricings REST API](https://learn.microsoft.com/en-us/rest/api/defenderforcloud/pricings).

### 보고서와 기존 결과

| 항목 | 계약 |
| --- | --- |
| 출력 | 실행별 `output/<실행시각-UTC>/`에 Excel·PPT·원본 JSON(raw·evidence·meta 통합). manifest는 자동 생성 시점의 파일 해시 기록 |
| PPT | Excel 6번의 SE·인터뷰 점수로 생성. 인터뷰 입력 후 `easm-agent deck`으로 갱신. [입력 절차](../README.md#중요---인터뷰-입력-후-ppt-재생성) |
| PPT 상세 표 | 인터뷰 질문·SE 수집 항목은 왼쪽 정렬. SE 표의 항목 번호와 실측 점수는 별도 열로 구분 |
| 실행 시각 | 마이크로초 포함 UTC·충돌 접미사를 폴더와 새 파일명에 동일 적용. 실제 수집 시각은 `collection.collected_at` 유지 |
| 시트 1~5 | 평가 템플릿의 기존 수식 캐시·메타데이터·사용자 강조·스타일·입력 점수·메모·민감도 레이블 보존. 시트 4 점수 자동 덮어쓰기 안 함 |
| 6. 수집 결과 | 시트 4의 A~F·서식·행 순서를 복사. G 수집 상태, I Level·평가기준, J 수집 내용·판정 근거, K 수집결과 링크, L 다음조치, M 평가 점수(1~5), N 검토메모. 판정 불가는 M 빈칸 |
| 근거 이동 | 6번 K의 수집결과는 같은 SE 코드의 7번 행으로 이동하는 통합 문서 내부 링크. 외부 URL·파일·사용자 입력을 링크 대상으로 쓰지 않음 |
| 원본·실패 | 7. 수집결과 근거, 8. 수집 Raw 데이터, 9. 수집이슈 Raw 데이터, 10. 필드누락사유. 원래 숫자·불리언·null·JSON 및 evidence_refs 보존 |
| 리소스 이름 | 6번 J·7번 요약은 최대 3개와 나머지 건수. 7번 하단 두 번째 표에 전체 이름·분류·구독·리소스 그룹·ID 기록. 동명은 ID로 구분하며 목록은 준수 증거가 아님 |
| 집계 | 인터뷰 54개·SE 31개 구조 유지. 시트 5 실제 집계는 시트 4 입력 기준이며 빈칸·N/A 제외. 4개 인터뷰 관점·SE 확보 시 영역, 6개 영역 확보 시 종합 산정 |
| 괴리 보정 | 인터뷰 평균 - SE 평균 >= 1.5이면 SE 평균 + 1.0으로 하향 보정, 소수 첫째 자리 반올림. 미확보를 0으로 보간하지 않음 |
| 템플릿 갱신 | `python -m scripts.merge_assessment --source <검토할-xlsx> --output <다른-경로.xlsx>`. 검토 후 사용하며 원본 덮어쓰기 금지. 패키지에도 템플릿 포함, 누락 시 오류 |
| 기존 결과 | `easm-agent package --output-dir output`은 최신 실행의 Excel·PPT 재생성. 특정 실행 폴더·기존 평면 구조 지원. 기본적으로 기존 파일명·판정 보존 |

## 고객 셋업·정리 계약

실행 명령·화면은 [README Step 1~5](../README.md#진행-순서)를 따릅니다. 미실행 인증·배포·삭제는 완료로 표시하지 않으며 캡처는 클릭 위치를 빨간 네모로 표시하고 식별자를 가립니다.

| 구분 | 계약 |
| --- | --- |
| 전달물 | [고객 ZIP](downloads/customer-setup.zip): `setup.sh`·`setup_account.py`·`foundry-reader.json`·`cleanup_account.py`. 공개 인증서는 별도 전달. 설정·개인키·인증서·수집기는 ZIP에서 제외 |
| ZIP 갱신 | `python -m scripts.package_customer_setup`. LF·고정 파일 목록 사용. 소스 일치·압축 해제 후 다중 구독 plan을 테스트 |
| 고객 실행 | Python 3.11 이상·Azure CLI·Bash. Python 표준 라이브러리만 사용하며 저장소·수집기 설치 불필요. 완료한 `setup.json`만 반환 |
| 인증 분리 | 고객은 관리자 인증 정보를 전달하지 않음. 개인키는 MS 보관. `verify`는 MS 저장소에서만 실행 |
| 설정 경로 | 고객 폴더는 같은 위치의 `setup.json`, 저장소는 `.easm-agent/setup.json` |
| `plan` | 계정 식별자의 실제 존재는 조회하지 않음 |
| `apply` | Client ID로 SP 조회 후 앱 이름·Client ID·SP 개체 ID 검증. 생략·오류 `principal_id`는 검증값으로 안내·저장. 조회·이름 검증 실패 시 쓰기 전 중단하며 이름 대체·새 SP 생성 금지. Client ID 없는 기존 명시 SP 방식 유지 |

| 권한 구분 | 관리자 apply 계약 |
| --- | --- |
| Azure 읽기 | 승인 구독마다 Reader·Cost Management Reader·Log Analytics Reader·Security Reader |
| Foundry 읽기 | `EASMAgent Foundry Evidence Reader v2`를 승인 구독에 할당해 기존·이후 프로젝트에 상속. `--foundry-project-scopes`로 승인 프로젝트 제한 가능 |
| Foundry DataActions | `agents/read·evaluations/read·assets/read` 3개만. 역할 생성·할당은 관리자 예외이며 수집기가 수행하지 않음 |
| Graph 앱 읽기 | `AgentIdentity.Read.All`, `AgentIdentityBlueprint.Read.All`, `Application.Read.All`, `CopilotPackages.Read.All` 및 테넌트 관리자 동의 |
| 최소 권한 | 진단 SP에 Owner·Contributor·Foundry User 등 쓰기 역할 부여 금지. Graph 관리자 동의 권한은 구독 역할 할당 권한과 별개 |

| 예외·안전 처리 | 계약 |
| --- | --- |
| Graph 동의 | `requiredResourceAccess`와 실제 appRoleAssignments를 일치시키되 기존 타 API 권한은 보존. 필요한 `Role`만 추가. [CLI 권한 추가](https://learn.microsoft.com/en-us/cli/azure/ad/app/permission?view=azure-cli-latest#az-ad-app-permission-add) |
| 동의 실패 | Azure 역할 성공과 별도로 미완료 표시. 활성 Privileged Role Administrator/Global Administrator 필요(Global Reader 불가). PIM 활성화 후 `bash setup.sh login --login-resource graph`로 갱신·재실행. 오류는 고정 코드만 표시하며 본문·토큰 미출력. [Graph 권한](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-post-approleassignments?view=graph-rest-1.0) |
| 인증서 경로 | `.easm-agent/certificate-path`를 재사용. 기록이 없으면 `auth-*/diagnostic.pem`이 정확히 하나일 때만 선택. 부재·다중 후보·잘못된 기록은 오류. 경로 도우미는 개인키 내용을 읽지 않음 |
| 사전 점검 | 대상 없음·endpoint 미지정은 `NOT_CHECKED/not_found`이며 성공 아님. 이 사유만 있으면 종료 0·수집 계속. DENIED·ERROR·FEATURE_UNAVAILABLE는 종료 2. 정식 수집은 프로젝트 자동 발견 |

| 정리 단계 | 안전 계약 |
| --- | --- |
| cleanup-plan | 삭제 없이 실제 대상 조회. 완료된 setup.json의 테넌트·Client ID·SP 개체 ID·진단 전용 앱 이름과 Single tenant/Application 유형 검증 |
| cleanup-apply | 승인 구독의 해당 SP 역할 할당을 먼저 회수. 앱·SP 부재를 재조회한 뒤 정확히 일치하는 진단 사용자 지정 역할만 정리 |
| 역할 보존 | 다른 주체의 활성·PIM 적격 할당 또는 재사용 계획이 있으면 보존. 조회 실패를 미사용으로 간주하지 않음 |
| PIM 조회 | 현재 적격 인스턴스와 향후 적격 예약의 모든 페이지 검사. plan의 `delete_after_target_assignments`는 해당 SP 할당 회수 후에만 삭제 가능하다는 뜻 |
| 삭제 직전·직후 | 삭제 직전 사용 여부 재조회. 역할 DELETE 후 승인 구독 전체의 동일 역할 ID 부재를 최대 6회 확인. 전파 대기 중 DELETE 반복 금지. 조회 실패·지속 존재는 성공 아님 |
| 종료 확인 | SP 삭제만으로 RBAC 제거를 가정하지 않음. 홈 테넌트 앱·SP 잔여와 Graph 동의 철회 확인. Step 5 Delete 캡처는 위치 안내이며 삭제 완료 증거 아님 |
| 로컬 정리 | 인증서·개인키·암호 환경변수·경로 기록·setup.json·CLI 세션·공유 보고서·증적 사본을 승인 보관 정책에 따라 정리. 임시 PIM 종료, 데모 종속 ID 보존 |
| 별도 승인 | 스크립트는 영구 삭제·파일 폐기·데모 삭제 안 함. 삭제 앱은 30일 복원 가능할 수 있으며 완전 폐기는 고객 승인 후 별도 수행 |

공식 근거: [PIM 적격 인스턴스 2020-10-01](https://learn.microsoft.com/en-us/rest/api/authorization/role-eligibility-schedule-instances/list-for-scope?view=rest-authorization-2020-10-01), [향후 적격 예약 2020-10-01](https://learn.microsoft.com/en-us/rest/api/authorization/role-eligibility-schedules/list-for-scope?view=rest-authorization-2020-10-01), [앱 삭제](https://learn.microsoft.com/en-us/entra/identity-platform/howto-remove-app), [복원·영구 삭제](https://learn.microsoft.com/en-us/entra/identity-platform/howto-restore-app), [SP 삭제 후 RBAC](https://learn.microsoft.com/en-us/azure/role-based-access-control/troubleshooting#symptom---role-assignments-with-identity-not-found), [사용자 지정 역할 삭제](https://learn.microsoft.com/en-us/azure/role-based-access-control/custom-roles#delete-a-custom-role).

## 공식 API와 읽기 계약

- 현재 Azure Public Cloud만 지원하며 소버린 클라우드 호스트·audience는 추측하지 않습니다. 실행 의존성은 `pyproject.toml`의 azure-identity·requests이며 아래 SDK 버전은 REST 확인 근거이지 설치 요구가 아닙니다.
- 2026-11-03 승인 샘플에서 신규 API·수집을 검증했습니다(Python 3.11.18, azure-ai-projects 2.4.0, openai 2.54.0). 모든 고객 서비스·버전 지원을 보장하지 않습니다.
- 구독별 병렬 실행·전체 페이지·429/일시 오류 재시도·부분 실패를 유지합니다. API 증거는 `evidence/<timestamp>/`에 저장하기 전에 비밀·토큰·연결문자열·개인 식별 정보를 마스킹합니다.

| 조회 | 경로·버전·근거 | 계약·한계 |
| --- | --- | --- |
| 구독 | GET `/subscriptions`, `2022-12-01`. [List](https://learn.microsoft.com/rest/api/resources/subscriptions/list?view=rest-resources-2022-12-01) | 지정 테넌트 Enabled 구독 |
| 유효 권한 | GET `/subscriptions/{id}/providers/Microsoft.Authorization/permissions`, `2022-04-01`. [List](https://learn.microsoft.com/rest/api/authorization/permissions/list-for-scope?view=rest-authorization-2022-04-01) | 광범위·명시적 쓰기 권한 안전 가드이지 완전한 IAM 감사 아님 |
| 리소스 | GET `/subscriptions/{id}/resources`, `2021-04-01`. [List](https://learn.microsoft.com/rest/api/resources/resources/list?view=rest-resources-2021-04-01) | ARM nextLink 처리·Resource Graph 보완 |
| 프로젝트 ARM | `accounts/projects`, `2025-06-01`. [공식 스펙](https://github.com/Azure/azure-rest-api-specs/blob/main/specification/cognitiveservices/resource-manager/Microsoft.CognitiveServices/CognitiveServices/stable/2025-06-01/cognitiveservices.json) | 관리 평면·데이터 평면 구분 |
| 신규 Agent | project endpoint GET `/agents`, `/agents/{name}/versions`, `api-version=v1`. [SDK 2.4 샘플](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_2.4.0/sdk/ai/azure-ai-projects/samples/agents/sample_agent_basic.py) | data/last_id/has_more 페이지 처리. 논리 Agent당 1건, 최신 보이는 버전이 운영 배포라고 주장하지 않음 |
| 평가 | GET `/openai/v1/evals`, `/openai/v1/evals/{id}/runs`. [안내](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluate-agent) | 완료 상태의 프로젝트 이력. completed_at 없으면 생성 시각으로 대체하지 않음. 질문·응답·데이터셋 본문 미조회 |
| 모델 배포 | GET `{accountResourceId}/deployments`, `2024-10-01`. [List](https://learn.microsoft.com/rest/api/aiservices/accountmanagement/deployments/list?view=rest-aiservices-accountmanagement-2024-10-01) | model·versionUpgradeOption·raiPolicyName은 구성값. 정책 효과·모델 승인 아님 |
| 콘텐츠 필터 | GET `{account}/raiPolicies`, `2024-10-01`. [List](https://learn.microsoft.com/rest/api/aiservices/accountmanagement/rai-policies/list) | 실제 정책과 필터 활성 대조. 미지정 정책명을 실제 안전 통제 부재라고 단정하지 않음 |
| 호스트 구성 | GET `sites/{name}/config/web`, `2024-04-01`. [Get Configuration](https://learn.microsoft.com/rest/api/appservice/web-apps/get-configuration) | 인바운드 기본 제한·런타임. 앱 설정 list는 비밀 반환 가능해 호출하지 않음 |
| ARM 역할 | GET `/subscriptions/{id}/providers/Microsoft.Authorization/roleAssignments`, `2022-04-01`. [List](https://learn.microsoft.com/rest/api/authorization/role-assignments/list-for-subscription) | 관리 ID의 동일 구독 직접 할당과 Graph 앱 역할 구분 |
| Resource Graph | 읽기 query POST, `2022-10-01`. [Resources](https://learn.microsoft.com/rest/api/azureresourcegraph/resourcegraph/resources/resources?view=rest-azureresourcegraph-resourcegraph-2022-10-01) | Resources·PolicyResources·SecurityResources 조회. [지원 테이블](https://learn.microsoft.com/azure/governance/resource-graph/reference/supported-tables-resources#securityresources) |
| 보안 권고 | SecurityResources assessments의 resourceDetails.Id·status.code | 조회 성공·빈 결과가 Defender AI 기능·라이선스 활성화 증거는 아님 |
| 보안 점수 참고 | GET `/subscriptions/{id}/providers/Microsoft.Security/secureScores`, `2020-01-01`. [안내](https://learn.microsoft.com/azure/defender-for-cloud/secure-score-security-controls#get-your-secure-score-from-the-rest-api) | `ascScore`, `score.current/max/percentage`(0~1) 실측. 현재 BI-SY-12 등급에는 미사용 |
| 진단 설정 | GET `{resourceId}/providers/Microsoft.Insights/diagnosticSettings`, `2021-05-01-preview`. [List](https://learn.microsoft.com/rest/api/monitor/diagnostic-settings/list?view=rest-monitor-2021-05-01-preview) | Agent 관련 실행 로그만. 구독 Activity Log는 `log_scope_exclusions`로 제외하며 조회 안 함 |
| workspace | GET `{workspaceResourceId}`, `2022-10-01`. [Get](https://learn.microsoft.com/rest/api/loganalytics/workspaces/get?view=rest-loganalytics-2022-10-01) | 보존 설정과 실제 로그·보호 테이블 권한 구분. 승인 구독 밖 sink는 권한 확대 없이 permission_denied |
| 메트릭 | GET `{resourceId}/providers/Microsoft.Insights/metrics`, `2018-01-01`. [List](https://learn.microsoft.com/rest/api/monitor/metrics/list?view=rest-monitor-2018-01-01) | metricDefinitions와 수치 표본 확인. timespan은 UTC `YYYY-MM-DDTHH:MM:SSZ`로 보내 `+` 재해석 방지 |
| 로그 query | Log Analytics query·AppServiceConsoleLogs. [열 정의](https://learn.microsoft.com/azure/azure-monitor/reference/tables/appserviceconsolelogs) | ResultDescription의 샘플 이벤트 집계. 누락 호출·토큰을 0으로 만들지 않음 |
| 비용 | POST `/subscriptions/{id}/providers/Microsoft.CostManagement/query`, `2023-03-01`. [Query Usage](https://learn.microsoft.com/rest/api/cost-management/query/usage?view=rest-cost-management-2023-03-01) | Daily·ResourceId·UsageDate·Cost·Currency. App Service site와 serverFarmId 대조, 공유 모델·모니터링 비용 중복 귀속 금지 |
| 예산 | GET `/subscriptions/{id}/providers/Microsoft.Consumption/budgets`, `2023-05-01`. [List·필드 정의](https://learn.microsoft.com/en-us/rest/api/consumption/budgets/list?view=rest-consumption-2023-05-01) | `properties.amount·category·timePeriod.startDate/endDate·filter·notifications` 확인. notifications의 `enabled·threshold·thresholdType=Actual/Forecasted`와 `contactEmails·contactGroups·contactRoles` 존재 확인. 수신자 값 대신 존재 여부·개수만 저장 |
| 작업 그룹 | GET `{actionGroupResourceId}`, `2021-09-01`. [Get·필드 정의](https://learn.microsoft.com/en-us/rest/api/monitor/action-groups/get?view=rest-monitor-2021-09-01) | `properties.enabled`와 `emailReceivers·smsReceivers·webhookReceivers·armRoleReceivers·azureFunctionReceivers·logicAppReceivers·itsmReceivers` 대조. 수신자 status가 있는 유형은 Enabled 확인. 그룹 비활성·수신자 비활성은 전달 경로 충족 아님 |
| 정책 할당 참고 | GET `/subscriptions/{id}/providers/Microsoft.Authorization/policyAssignments?$filter=atScope()`, `2023-04-01`. [List](https://learn.microsoft.com/rest/api/policy/policy-assignments/list?view=rest-policy-2023-04-01) | 할당·enforcementMode만으로 Deny 효과·자동 교정 추론 금지. 모델 허용 목록 등급에 미사용 |

### Foundry 역할과 초기 프로필

- [Foundry RBAC](https://learn.microsoft.com/azure/foundry/concepts/rbac-foundry)의 Reader는 관리 평면만 허용합니다. [평가 권한 안내](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluation-permissions)는 최소 읽기 역할 보장이 아닙니다.
- [Foundry User](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/ai-machine-learning#foundry-user)는 `accounts/listkeys/action`, `Microsoft.Resources/deployments/*`, `Microsoft.CognitiveServices/*` 등 광범위 작업을 포함해 진단 계정에 부여하지 않습니다.
- [공식 공급자 작업](https://learn.microsoft.com/azure/role-based-access-control/permissions/ai-machine-learning#microsoftcognitiveservices)의 agents/read·evaluations/read를 확인했습니다. 신규 평가 목록 403에서 assets/read 요구를 실측해 v2 읽기 역할에 추가했으며 기존 v1은 변경하지 않았습니다. 수집기는 평가 관련 목록만 호출합니다.
- agents/read에는 threads/messages 읽기도 포함됩니다. 더 세밀한 Agent 메타데이터 전용 DataAction을 추측하지 않으며 실제 서비스 인가·테넌트 상태는 사전 점검으로 확인합니다. 사용자 지정 역할의 AssignableScopes는 입력 구독이며 현재 기본 할당은 승인 구독 상속입니다. [사용자 지정 역할 규칙](https://learn.microsoft.com/azure/role-based-access-control/custom-roles).
- 클래식은 명시적 `classic_v1`에서만 GET `/assistants?api-version=v1` 사용. [azure-ai-agents 1.1.0 연산](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agents_1.1.0/sdk/ai/azure-ai-agents/azure/ai/agents/operations/_operations.py), [설정](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agents_1.1.0/sdk/ai/azure-ai-agents/azure/ai/agents/_configuration.py).
- 초기 평가 `/evaluations/runs?api-version=2025-05-15-preview`는 이력이며 현재 신규 프로필로 자동 대체·역전환하지 않습니다. [azure-ai-projects 1.0.0b11 연산](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_1.0.0b11/sdk/ai/azure-ai-projects/azure/ai/projects/operations/_operations.py), [설정](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_1.0.0b11/sdk/ai/azure-ai-projects/azure/ai/projects/_configuration.py).
- Red team은 실제 읽기 SP의 공식 GET `/redTeams/runs?api-version=v1` 요청이 HTTP 401과 evaluations/write 요구로 거부되어 제외했습니다. 쓰기 권한 확대·일반 평가로 대체하지 않습니다.

### Entra Agent ID 계약

| 조회 | Graph v1.0 읽기 계약 |
| --- | --- |
| Blueprint | GET `/applications/microsoft.graph.agentIdentityBlueprint`, `AgentIdentityBlueprint.Read.All`. [공식 목록](https://learn.microsoft.com/graph/api/agentidentityblueprint-list) |
| Agent ID | GET `/servicePrincipals/microsoft.graph.agentIdentity`, `AgentIdentity.Read.All`. [공식 목록](https://learn.microsoft.com/graph/api/agentidentity-list) |
| 소유자·스폰서 | GET `/servicePrincipals/{id}/microsoft.graph.agentIdentity/owners` 또는 `/sponsors`, `$select=id,accountEnabled`. 사람 이름·UPN 없이 관계 수를 보관. accountEnabled는 기본 권한에서 제한될 수 있는 참고 속성이며 OE-SY-20 충족 조건에 미사용 |
| 앱 역할 | GET `/servicePrincipals/{id}/appRoleAssignments`, `Application.Read.All`. 대상 리소스 SP의 `appRoles`로 역할 이름 해석 |
| 제외 | 위임 동의는 Directory.Read.All로 범위를 넓혀야 하므로 수집 안 함. ARM 관리 ID를 Graph Agent Identity로 간주하지 않음 |

- 모든 Graph 진단 호출은 GET이며 `graph.microsoft.com`에만 토큰을 보냅니다. 2026-11-04 승인된 읽기 조회에서 Agent ID 9개·Blueprint 9개를 확인했으며 태그의 구독·계정·프로젝트·Agent 식별자로 매칭했습니다.

### 의미 해석의 공식 근거

| 주제 | 근거·한계 |
| --- | --- |
| 네트워크 | [AI 네트워크 규칙](https://learn.microsoft.com/en-us/azure/ai-services/cognitive-services-virtual-networks), [App Service VNet](https://learn.microsoft.com/en-us/azure/app-service/overview-vnet-integration), [App Service 접근 제한·Unmatched rule](https://learn.microsoft.com/en-us/azure/app-service/overview-access-restrictions#unmatched-rule). 명시 `ipSecurityRestrictionsDefaultAction`이 우선하며 미지정 시 규칙 0개는 허용, 1개 이상은 암묵적 거부. Any·0.0.0.0/0·::/0 Allow 규칙은 경계로 인정하지 않음. VNet 통합은 송신 경로이며 인바운드 차단 증거 아님 |
| MCP | [도구 승인](https://learn.microsoft.com/en-us/agent-framework/agents/tools/tool-approval), [MCP 도구](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/model-context-protocol). 승인 구성·HTTPS·allowed_tools는 런타임 우회 방지·송신 차단 보장 아님 |
| 콘텐츠 필터 | [기본값·설정](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/content-filters?view=foundry-classic). 기본 필터도 존재할 수 있어 raiPolicyName 미지정을 실제 필터 부재라고 단정하지 않음 |
| 모델 업데이트 | [버전·업데이트](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/model-versions?view=foundry-classic). NoAutoUpgrade는 영구 고정·퇴역 후 롤백 보장 아님 |
| 메타데이터 | [Agent 거버넌스](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai-agents/governance-security-across-organization). 상위 ARM 태그를 개별 Agent 승인으로 간주하지 않음 |
| 정책 평가 | [정책 효과](https://learn.microsoft.com/en-us/azure/governance/policy/concepts/effect-basics). Audit·Deny·Modify·DeployIfNotExists는 서로 다르며 준수 상태가 자동 교정을 입증하지 않음 |
| ID·로컬 인증 | [PIM 역할](https://learn.microsoft.com/en-us/entra/id-governance/privileged-identity-management/pim-resource-roles-assign-roles), [로컬 인증 비활성](https://learn.microsoft.com/en-us/azure/ai-services/disable-local-auth). 관리 ID 구성은 실제 사용·전체 최소 권한 증거 아님 |
| 관측·경보 | [trace 설정](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup), [작업 그룹](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/action-groups). 리소스·연결 존재가 실제 trace·전달·대응 성공 아님 |
| 지역·보존 | [모델 지역](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability), [테이블 보존](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/data-retention-configure). Global·Data Zone의 처리 지역과 workspace·테이블 보존 구분 |
| 예산 | [예산 동작·평가 주기](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets). 비용 갱신·평가 지연 존재. 예산은 통보 수단이며 초과 지출·리소스를 자동 중단하지 않음 |

## 관리자 데모의 공식 계약·실측 경계

이 절은 관리자 샘플 준비 이력이며 고객 진단의 쓰기 권한이나 현재 등급 근거가 아닙니다.

| 준비·검증 | 계약·공식 근거 |
| --- | --- |
| 웹 로그인 보호 | App Service `config/authsettingsV2`, ARM `2024-11-01`. 인증 필수·동일 tenant issuer·allowedPrincipals.identities, `/health`만 예외. [스키마](https://learn.microsoft.com/azure/templates/microsoft.web/sites/config-authsettingsv2) |
| 비밀번호 없는 로그인 | `OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID`, registration.clientSecretSettingName·앱 전용 User Assigned MI·Graph federatedIdentityCredential. [MI 로그인](https://learn.microsoft.com/azure/app-service/configure-authentication-provider-aad#use-a-managed-identity-instead-of-a-secret), [신뢰](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-config-app-trust-managed-identity) |
| 앱 등록 | Graph v1.0 applications·servicePrincipals·federatedIdentityCredentials. 단일 테넌트·승인 redirect URL·소유 표식이 있는 샘플 앱만 재사용. [앱](https://learn.microsoft.com/graph/api/application-post-applications?view=graph-rest-1.0), [연합 자격증명](https://learn.microsoft.com/graph/api/application-post-federatedidentitycredentials?view=graph-rest-1.0) |
| 샘플 평가 | OpenAI-compatible evals·runs, custom item_schema·string_check(eq)·jsonl/file_content로 실제 응답·정답 비교. 관리자만 terminal status·output_items 조회. [정의](https://learn.microsoft.com/azure/foundry/reference/rest/evals-create-eval), [실행](https://learn.microsoft.com/azure/foundry/reference/rest/evals-create-eval-run), [데이터셋](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-datasets) |
| 런타임 | SDK responses.create·LangChain create_agent. 웹 앱 MI가 추론하고 진단 SP는 추론하지 않음 |
| 인증서 | Graph application GET `$select=keyCredentials`로 기존 공개키를 보존하고 이번 임시 UUID만 추가·제거. 확보 불가 시 수정 안 함. 만료는 실제 not_valid_after_utc와 일치. [앱 갱신](https://learn.microsoft.com/graph/api/application-update?view=graph-rest-1.0), [keyCredential](https://learn.microsoft.com/graph/api/resources/keycredential?view=graph-rest-1.0) |
| 배포 확인 | 공식 Kudu ZIP의 이번 새 작업 ID·status=4·complete=true·실제 health 확인. 다른 origin·HTTP Location에 bearer 전송 금지. [Kudu API](https://github.com/projectkudu/kudu/wiki/Deploying-from-a-zip-file-or-url) |

<details>
<summary>과거 샘플 검증에서 확인한 제약</summary>

| 주제 | 확인·처리 |
| --- | --- |
| 모델 배포 | 목록·쿼터만으로 배포 가능성을 확정하지 않음. Korea Central의 `ServiceModelDeprecating` 이후 validate를 통과한 gpt-4.1-nano 2025-04-14 GlobalStandard 사용 |
| 패키징 | Oryx 지연으로 Linux wheel 사전 패키징. ELF x86_64·ZIP 무결성·새 revision·재시작 후 health를 별도 확인 |
| 웹 인증 | callback 401 확인 후 `response_type=code id_token`에 맞춰 ID 토큰·기본 동의 적용. access token implicit은 비활성 유지 |
| CSRF | no-referrer POST 403은 same-origin으로 해결. 플랫폼 CSRF 유지, forwarded 헤더 대신 WEBSITE_HOSTNAME의 HTTPS 원점 대조 |
| 인증·재시도 | 오래된 CLI CAE 토큰 대신 동일 관리자 DefaultAzureCredential 사용. 인증서 전파 `AADSTS700027`·모델 429만 제한 재시도. 진단 수집을 관리자 신원으로 대체하지 않음 |
| 해석 | 정확 일치 3문항은 종합 보안·품질 검증 아님. 실패 문항·비용 없음·범위 밖 로그·AI 권고 미확인의 원래 사유 보존 |
| 증거 경계 | 관리자 `published_at`·관측 시각은 운영 배포 증거가 아니며 Reader 판정에 주입하지 않음. 인증서 준비는 관리자만 수행하고 동일 앱의 동시 변경은 피함 |

</details>

## 미확정 범위와 이기종 Agent

- 게시·운영 배포 API와 Agent-평가-배포 lineage는 추가 검증이 필요합니다. created_at을 배포 시각으로 바꾸지 않으며 프로젝트 완료 평가를 배포 전 평가로 해석하지 않습니다.
- 메트릭 dimension의 Agent 식별력·90일 미사용 증명 가능성은 확정하지 않았습니다. 현재 지표는 리소스 단위 수치 표본 관측 범위입니다.
- Power Platform 값은 공식 PowerShell 모듈 `Microsoft.PowerApps.Administration.PowerShell`(2.0.220 이상)의 읽기 명령과 환경 목록 API로 별도 관리자가 내보냅니다. 비공식 BAP 호출을 직접 구현하지 않습니다.
- 모든 권한이 있어도 제품 기능·라이선스·데이터가 없을 수 있습니다. 403은 IAM·방화벽·Private Endpoint 모두 가능하며 permission_denied로 남기되 원인을 단정하지 않습니다. license_missing은 명시적 라이선스 상태 응답에만 사용합니다.
- LangChain 앱 설정 list는 비밀을 반환할 수 있어 기본 수집에서 호출하지 않습니다. 승인 태그·메타데이터 또는 명시적 CSV 입력을 사용합니다.
- 공통 AgentEvidence는 platform과 필드별 null 사유로 플랫폼 차이를 보존합니다. 같은 이름의 Foundry Agent도 platform·subscription_id·resource_id·agent_id 복합 키로 구분하며 비용·사용량의 공유 리소스 중복 귀속을 금지합니다.
- `easm-agent collect --manual-agents config/manual_agents.csv`는 manual/other 플랫폼의 직접 등록입니다. Google/AWS 자동 로그인 수집이 아닙니다. 최소 필드는 agent_id·agent_name·platform이며 날짜는 시간대 포함 ISO 8601, tags·tools·usage_30d·field_status는 JSON입니다.
- 빈 CSV 값은 null + not_found이며 0으로 채우지 않습니다. 수동 Agent는 인벤토리·플랫폼 개수에만 포함하고 Azure 전용 SE 분모에 섞지 않으며 CSV 행 evidence_refs로 API 실측과 구분합니다.
- 확장 Collector Protocol은 `discover(subscriptions)`와 `required_roles`를 사용합니다. 사례 커넥터 매핑·API Management AI Gateway·OpenTelemetry gen_ai 연계는 재사용 후보이며 구현·검증 완료로 표시하지 않습니다.

## Agent 365 등록부 교차검증

| 항목 | 계약 |
| --- | --- |
| 읽기 API | `GET https://graph.microsoft.com/v1.0/copilot/admin/catalog/packages`. 서버의 `@odata.nextLink`를 변경 없이 순회하며 동일 경로·신뢰 호스트·반복 링크 가드와 기존 재시도 적용 |
| 권한·라이선스 | Application `CopilotPackages.Read.All`과 관리자 동의, Agent 365 라이선스 필요. 실제 테넌트의 사용 가능 여부는 수집 응답으로 확인 |
| 데이터 최소화 | 문서에 없는 `$select`는 사용하지 않음. 메모리에서 패키지 `id`, `agentIdentityId`, `version`, `displayName`, `platform`, `availableTo`, `deployedTo`, `isBlocked`, `createdDateTime`, `requestStatus`, `governanceMetadata`와 `owners` 건수만 선별. displayName은 리소스 이름으로 보관하며 사람 정보·게시자·설명·사용자/그룹 ID 목록·본문은 미저장 |
| DS-SY-05 | 등록부의 명시적 `agentIdentityId`가 Graph Agent ID·Blueprint 참조로 연결되는지만 대조. 완전한 Graph 목록과 모순되는 참조는 불일치, 필수 필드 누락은 미확인 |
| DP-SY-19 | 기존의 구독·계정·프로젝트·Agent 태그로 식별된 유일한 Graph ID와 등록부의 명시적 ID 대조. 미게시·동명이인·다중 연결은 이름으로 추정하지 않고 미확인 |
| 나머지 21개 | `동일 정보 미제공`: 기존 Azure/Graph API로 평가하되 Agent 365 등록부에 같은 판정 정보가 없어 추가 대조하지 않음. 평가 제외를 뜻하지 않음 |
| 상태·등급 | 일부 일치 / 불일치 / 미확인 / 동일 정보 미제공. 비교 범위·건수·사유·증적은 별도 표시하고 기존 Level·점수는 변경하지 않음 |
| 실패 | 권한·명시적 라이선스·기능·응답 오류는 원래 사유로 기록. 완전하지 않은 등록부를 빈 목록·0점·일치로 처리하지 않음 |
| 출력 | 7번 J~L 교차검증 열, 8번 등록부·대조 Raw 테이블 추가. 기존 결과를 package로 재생성할 때는 교차검증을 실행하지 않으며 `미수행` 표시 |
| SDK와의 구분 | 승인된 구현은 관리 API 읽기 방식. 런타임 Agent 365 SDK·OpenTelemetry 삽입, Agent 재배포·등록·알림·도구 실행은 수행하지 않음 |
| 화면 확인 | 2026-11-09 M365 Admin Center에서 Foundry Agent의 Details·Entra agent ID 표시를 실제 확인. 화면 확인은 진단 SP의 공개 API 호출 성공 증거가 아님 |
| 실수집 확인 | 2026-11-09 인증서 SP에 Graph 읽기 권한 4개 동의 확인 후 2회 조회. 최종 Azure 수집 이슈는 없고 등록부 API만 HTTP 403. 교차검증은 `permission_denied`·미확인으로 보존하며 라이선스 원인으로 단정하지 않음 |

- [List packages](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/admin-settings/package/copilotpackages-list), [패키지 필드](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/admin-settings/package/resources/copilotpackage)
- [Agent 365 SDK](https://learn.microsoft.com/en-us/microsoft-agent-365/developer/agent-365-sdk), [Foundry 연동](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/agent-365-integration)
- 패키지 `version`은 Foundry Agent·호스트 런타임 버전과 다른 값입니다. UI의 Owner·활동 통계도 공개 등록부 API의 동일 필드 제공을 보장하지 않습니다.

## 등록부·관리자 읽기 5+3개 항목의 계산 범위

계산식·한계는 [31개 API 지표](#31개-api-지표)를 따릅니다. 등록부 5개와 관리자 읽기 3개의 증적 원천을 구분하며, 진단 SP에 관리자 권한을 부여하지 않습니다.

- 등록부 5개는 Agent 365 라이선스·`CopilotPackages.Read.All`이 없으면 `permission_denied` 등 원래 사유와 `null`로 유지하며 L1·0%로 바꾸지 않습니다. 등록부가 비어 있거나 조회가 미완료인 경우도 같습니다.
- 관리자 읽기 3개는 별도 관리자 증적이 없으면 판정 보류입니다. 내보내기에는 환경별 역할 건수(`role_counts`)와 정책 적용 범위(`policies`)만 포함하며 사람·정책 내용은 저장하지 않습니다.
- [Power Platform 환경 목록 API 2024-10-01](https://learn.microsoft.com/en-us/rest/api/power-platform/environmentmanagement/environments/list-environments-for-user), [Agent 설정 화면](https://learn.microsoft.com/en-us/microsoft-agent-365/admin/agent-settings)

## 관리자 읽기 내보내기

진단 SP 대신 승인된 관리자가 별도로 실행하는 읽기 전용 도구입니다. 모듈 설치·역할 부여·정책 변경은 수행하지 않습니다. Power Platform 관리 SP 등록은 테넌트 관리자 수준 권한을 부여하므로 진단 SP에 적용하지 않습니다.

| 원천·계약 | 보관 값·한계 |
| --- | --- |
| 환경 GET, API 2024-10-01 | Azure CLI 관리자 사용자 로그인. 관리자 접근 가능 환경의 id·displayName·type·protectionLevel·azureRegion만 저장. 누락 필드는 `null`, `@odata.nextlink` 전체 페이지 확인 |
| Microsoft.PowerApps.Administration.PowerShell 2.0.220 이상 | Add-PowerAppsAccount 후 Get-AdminPowerAppEnvironmentRoleAssignment·Get-AdminDlpPolicy. 비 Dataverse 환경별 역할 할당 건수와 DLP 정책의 환경 적용 범위(`FilterType`·환경 ID)만 저장 |
| 실패·출처 | 모듈 부재는 feature_unavailable, 조회 실패는 건수 `null`. JSON의 테넌트·시간·명령·모듈 버전·범위를 확인하고 마스킹된 증적과 SHA256 보관. 해시는 원천 인증 서명이 아님 |

저장소를 준비한 별도 관리자 터미널에서 실행합니다. PowerShell 도구는 공식 모듈이 미리 설치되어 있어야 합니다. 로그인 방식은 아래 표와 같으며 토큰은 파일·증적에 저장하지 않습니다.

| 도구 | 데스크톱 | 창이 없는 터미널(Codespaces·SSH·원격) |
| --- | --- | --- |
| 환경 내보내기 | `az login --tenant <테넌트-ID>` | `az login --tenant <테넌트-ID> --use-device-code` |
| Power Platform (`-Service PowerPlatform`) | `-Login Interactive`(기본) 또는 `-Login Browser`(`-UseSystemBrowser`) | 공식 모듈에 장치 코드 로그인이 없어 `feature_unavailable`로 기록. 데스크톱에서 실행한 JSON을 사용 |

- `-Login Auto`(기본)는 `CODESPACES`·`SSH_CONNECTION`·`SSH_TTY` 설정, 비대화형 세션 또는 Linux의 디스플레이 부재를 창 없는 환경으로 보고 `DeviceCode`를 선택합니다. 그 외에는 `Interactive`입니다.

```powershell
python scripts\export_admin_environments.py --tenant-id <테넌트-ID> --output .easm-agent\admin-exports\environments.json
.\scripts\export_admin_evidence.ps1 -TenantId <테넌트-ID> -Service PowerPlatform -OutputPath .easm-agent\admin-exports\powerplatform.json -Login Browser
```

관리자 JSON만 전달하고 기존 결과에 반영합니다. 원래 Azure 수집 시각은 유지되며 각 관리자 조회 시각을 별도로 기록합니다. 원본 증적이 내장된 이식형 결과에는 해당 실행 폴더의 `evidence/<내보내기반영시각>/`에 새 증적을 보관합니다. 새 수집에서도 같은 `--admin-evidence-file`을 반복 지정할 수 있습니다.

```powershell
easm-agent package --output-dir output\<실행폴더> --tenant-id <테넌트-ID> `
  --admin-evidence-file .easm-agent\admin-exports\environments.json `
  --admin-evidence-file .easm-agent\admin-exports\powerplatform.json --reassess
```

- `--reassess`는 첨부한 증적을 등급에 반영합니다. `package`는 Excel을 새로 만들므로 인터뷰 입력본을 먼저 별도 보관합니다.
- 2026-11-10 실측: 환경 API 200·접근 가능 환경 1개. 로컬 PowerApps 모듈 부재로 역할·정책은 미수집이며, 완료했다고 표시하지 않습니다.
- 공식 근거: [역할 할당 조회](https://learn.microsoft.com/en-us/powershell/module/microsoft.powerapps.administration.powershell/get-adminpowerappenvironmentroleassignment), [DLP 정책 조회](https://learn.microsoft.com/en-us/powershell/module/microsoft.powerapps.administration.powershell/get-admindlppolicy), [관리 SP 권한 한계](https://learn.microsoft.com/en-us/power-platform/admin/powershell-create-service-principal).
