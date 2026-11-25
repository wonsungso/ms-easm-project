# API·평가 기준 참고

| 찾을 내용 | 위치 |
| --- | --- |
| 실행·권한 설정·정리 | [README](../README.md) |
| 항목별 설명·확인 화면 | [점검 항목 상세](checklist.md) |
| 지표·분모·증거·한계·등급 규칙 | [criteria.yaml](../config/criteria.yaml)의 `grading_profile: api_configuration_v1` |
| 읽기 API·버전·공식 근거 | [공식 API 계약](#공식-api와-읽기-계약) |
| 별도 관리자 증적 | [내보내기 절차](#관리자-읽기-내보내기) |
| PPT 작성 규칙 | [PPT 작성 지침](#ppt-작성-지침) |
| 테스트 환경 배포 | [개발용 데모](../demo/README.md) |

승인된 과거 원본은 Git 제외 로컬 `source-materials/`에 보관하며 실행에 필요하지 않습니다. 과거 원문 Level·구성 L2 기본등급은 현재 평가에 사용하지 않습니다.

## 범위 원칙

용어는 MS Learn의 [소유자·스폰서·관리자](https://learn.microsoft.com/ko-kr/entra/agent-id/agent-owners-sponsors-managers), 에이전트 ID 청사진, [민감도 레이블](https://learn.microsoft.com/ko-kr/purview/sensitivity-labels)을 사용합니다. API 키·실제 메뉴·리소스 이름은 유지합니다.

| 구분 | 범위·처리 |
| --- | --- |
| 수집·평가 | Microsoft Foundry, Azure 자체 호스팅 Agent, Azure Monitor·Log Analytics, 비용·보안 권고, Defender for Cloud 플랜, Entra Agent ID, Power Platform 관리자 읽기의 26개 항목 |
| Copilot 인벤토리 | Agent Builder·Copilot Studio를 별도 `copilot_agents`로 수집. 26개 안의 모델·접근·도구·평가·보안·게시·신원·소유자·인증 항목에 플랫폼별로 포함 |
| Entra 필수 조회 | DS-SY-03, DP-SY-15, OE-SY-16~17. 생략 옵션 없이 권한 부족은 항목을 유지하고 `null`과 사유 기록 |
| 관리자 읽기 3개 | DM-SY-01·DS-SY-02·BI-SY-08. 승인된 관리자의 별도 읽기 내보내기 증적을 사용하며 진단 SP 권한은 확대하지 않음 |
| 자체 Agent 탐지 | 승인 구독의 App Service·Container Apps·AKS. 기본 LangChain 조건에 사용자 태그 OR 조건 추가. 태그만 일치하면 `custom` 후보이며 실행 증거는 아님. [설정 예시](../README.md#자체-agent-탐지-태그) |
| 승인 경계 | 지정 테넌트의 접근 가능한 구독을 기본 열거하고 CLI·설정의 승인 범위를 적용. 외부 workspace·청구 범위로 자동 확대하지 않음 |
| 실행 신원 | 진단 SP의 DefaultAzureCredential. Reader 중심 GET 및 Resource Graph·비용·로그의 읽기 query POST만 허용 |
| 보안 권고 범위 | 현재 발견한 AI 리소스·하위 리소스로 Resource Graph 요청과 응답을 제한. 삭제·무관 리소스 권고는 제외 |
| 관리자 예외 | `scripts/setup.sh`, `setup_account.py`, 정리 스크립트와 demo만 승인된 배포·역할·일회성 인증 준비 수행. 수집기에서 import 금지 |
| 결과 번호 | `assessment_revision: 7`은 `XX-SY-NN` 연속 번호 01~26. Demand 01, Design 02~07, Build 08~14, Deploy 15, Operate 16~22, Optimize 23~26 |
| 제외 API | Red team·조건부 접근·위험 Agent 진단 제외 |

## 판정 근거와 재현성

| 결과 위치 | 확인할 내용 |
| --- | --- |
| `findings[].evidence_refs` | 해당 항목의 조회·계산에 직접 사용한 증적 |
| `findings[].measurement` | 분자·분모, 개수/금액 구분, 통화, 계산 완료 여부와 보류 사유. 실패·미확인·빈 분모는 계산값 `null` 유지 |
| `measurement.targets[]` | 대상 식별자, 확인 값, 충족·미충족·미확인·계산 제외 상태, 계산 기여값과 증적 참조 |
| `collection.evidence_sources` | API 요청 주소와 증적 참조의 연결. 여러 페이지 조회도 같은 원천으로 연결 |
| `provenance.references` | 연결된 증적을 `evidence:<SHA256>`로 표시. 로컬 절대 경로 대신 SHA256을 보관해 재패키징 시 연결 유지 |
| `collection.assessment_provenance` | 평가 시각, 마스킹된 평가 기준·태그 규약의 사본과 SHA256, 수집기 패키지 버전·Python 소스 묶음의 SHA256 |
| 부분 증적 갱신 | Azure 기존 실측과 새 관리자 읽기를 구분. 원천별 관측 시각과 재평가 출처를 보존하며 Raw 추출 일시는 항목에 사용한 최신 증적 시각. 전체 재수집으로 표시하지 않음 |
| Excel 3_SE 판정 | 26개 API 등급·충족률·판정 근거. L5는 API 구성·기록 100% 충족이며 조직 전체 성숙도·정책 실효성의 증명이 아님 |
| Excel 4_프로세스 점수 | F열 수동 응답, G/H/I열 확인 증적, M열 근거. 미입력 응답은 0점이 아님 |
| Excel 수집결과 근거 | 항목 요약·전체 리소스 목록·대상별 판정·평가 출처. 비용은 건수가 아닌 금액·통화로 확인 |
| PPT 요구 지표 대조표 | 수집결과 근거 시트 하단에 원본 PPT 20개 요구 지표와 현재 SY의 범위 차이·보류 사유 보관 |
| 보고서 지표 | PPT의 안정된 키·관측값·사유·범위·증적 계약. 저장된 raw JSON 수집 결과로 PPT 생성 때 계산. `report_groups`는 표시 분류이며 등급 규칙 아님 |

## Copilot 인벤토리 읽기 계약 (2026-11-19 문서 확인)

관리자 전용 데모의 Dataverse 사전 점검은 [사용자 환경 목록](https://learn.microsoft.com/en-us/rest/api/power-platform/environmentmanagement/environments/list-environments-for-user) `2024-10-01`의 `id`, `tenantId`, `dataverseId`, `url`을 Dataverse `WhoAmI` 조직 ID와 대조합니다. 페이지가 남거나 값·접근이 불확실하면 배포를 중단합니다. 이 조회는 진단 수집기의 권한·등급과 별개입니다.

| 구분 | 확인한 계약 |
| --- | --- |
| API | `POST https://api.powerplatform.com/resourcequery/resources/query?api-version=2024-10-01` |
| 쿼리 | `TableName=PowerPlatformResources`, `type == microsoft.copilotstudio/agents`. 쓰기·격리·배포 API 호출 없음 |
| 인증 | `https://api.powerplatform.com/.default`의 위임 사용자. SP·관리 ID는 공식적으로 403 |
| 읽기 역할 | 별도 사용자의 `Global Reader` 또는 `AI Reader`. 진단 SP에 부여하지 않음 |
| 페이지 | `Options.Top/SkipToken`, 응답 `totalRecords/count/resultTruncated/skipToken/data`. 반복 토큰·잘림·건수 불일치·중복은 실패 |
| 잘림 플래그 | `resultTruncated`는 SDK 정수 enum(`0=잘림`, `1=잘림 아님`)이며 true/false로 변환하지 않음 |
| 저장 | 최소 필드 projection. 소유자는 nullable 존재 여부로만 저장. 사용자 ID·콘텐츠·토큰·페이지 토큰 제외 |
| Agent ID | `properties.name`(Dataverse Bot ID)이 있으면 사용하고 null이면 최상위 `name`을 사용. 두 값의 일반적인 동등성은 추론하지 않음 |
| 소유자 존재 | nullable projection 응답은 `true`/`false` 외 정수 `1`/`0`도 반환. 해당 정수만 Boolean으로 변환하고 null은 유지 |
| 출처 구분 | `createdIn`의 확인된 작성 도구만 대소문자 구분 없이 분류. Agent Builder는 `Microsoft Copilot Agent Builder`, `Microsoft 365 Copilot Agent Builder`, 관측된 `Copilot Studio Lite`를 인정(공식 스키마에 값 목록이 없어 변경 가능). 미확인 값은 `unclassified_copilot` |
| 적용 범위 | V2 Agent의 초안·게시 인벤토리. 구성은 게시 버전 기준이며 최신 미게시 변경 전체를 뜻하지 않음 |
| 반영 지연 | 대체로 20분 이내. 리소스 종류별 capability 최대 200개이므로 완전한 도구 분석으로 사용하지 않음 |
| Agent Builder 신원 | 공식 스키마상 Agent ID·청사진 필드 미적용. 미지원 필드를 통제 실패로 채점하지 않음 |
| 하니스·오케스트레이션 | 공식 `properties.harness`·`properties.orchestration`을 원문으로 보존. 하니스 표시값을 임의로 Standard로 변환하지 않음 |
| 커넥터 | `powerPlatformConnectors`의 connectorId·operationId·isEnabled·requiresEndUserConsent·connectionProvider·whenCanBeUsed만 보존. createdBy·연결 ID 제외. 명시적 전체 건수와 일치하지 않거나 200개 제한을 넘으면 보류 |
| 기존 평가 GET | `2024-10-01` `/copilotstudio/environments/{EnvironmentId}/bots/{BotId}/api/makerevaluation/testruns`. Standard 하니스만 조회. ID·state·endTime·totalTestCases만 보존하며 테스트 입력·응답·소유자·설명 제외 |
| 평가 상태 | `Completed`와 종료 시각을 확인. 성공한 빈 실행 목록은 완료 기록 0건. 조회 실패·미확인 상태는 null과 사유. 새 평가 run POST 금지 |
| Agent Readiness | [Agent status](https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-agent-status)는 Standard 하니스용 미리 보기이며 관리자 거버넌스 보고서를 대체하지 않음. 이 문서에 준비 상태 읽기 API가 없어 추측 호출하지 않음 |
| 실제 검토 화면 | Standard 외 하니스에서도 실제 `문제 검토` 패널이 보이면 별도 승인 화면 증적으로 보존. `No evaluation run`은 완료 평가 없음의 근거로만 반영하고 Standard API 지원을 추론하지 않음 |
| 검토 파일 계약 | `--copilot-review-file`의 schema_version=1, source_type=official_admin_portal_read, approved·tenant_verified=true, tenant_id·exported_at·reviews 필요. 각 행은 agent_id·environment_id·정확한 source_url·observed_at·state=authoring, 선택 warning_count·evaluation_run_missing·channel_configuration_missing. 최근 24시간·중복·테넌트 검증. 메시지 원문·사람·테스트 콘텐츠 제외 |
| 검토와 API 충돌 | API에 완료 실행이 있지만 화면은 실행 없음이면 판정 보류. 화면에 평가 실행 없음이 아닌 경우 완료 평가를 추론하지 않음. 다른 Agent·환경 화면은 사용하지 않음 |
| 가져오기 | 테넌트 일치·승인 표시·최근 24시간·완료·건수·중복·시각 검증. 로컬 승인 증적이며 암호학적 서명은 아님 |
| 실패 | 403만으로 라이선스 부재를 추론하지 않음. 명시적 `not licensed` 응답만 `license_missing`; 실패 목록·건수는 null |
| 구독 없는 실행 | `collect --copilot-only`는 로컬 증적만 읽고 Azure·Graph·자격 증명에 접근하지 않음. Azure 지표는 미측정 유지 |

| 공식 근거 | 용도 |
| --- | --- |
| [Copilot Studio 보안 및 거버넌스](https://learn.microsoft.com/ko-kr/microsoft-copilot-studio/security-and-governance) | 인벤토리·소유권·인증 구성의 거버넌스 맥락 |
| [구현 점검 목록](https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/implement-checklist) | 모델·오케스트레이션·도구·인증·채널 검토 근거 |
| [자동 보안 검사](https://learn.microsoft.com/en-us/microsoft-copilot-studio/security-scan) | 무인증·제작자 자격 증명·전체 조직 공유의 위험 구성 근거 |
| [하니스](https://learn.microsoft.com/en-us/microsoft-copilot-studio/harnesses-overview) | 기능·준비 상태·평가의 런타임별 범위 |
| [기존 평가 목록 GET](https://learn.microsoft.com/en-us/rest/api/power-platform/copilotstudio/bots/list-maker-evaluation-test-runs) | 공식 endpoint·2024-10-01·응답 상태 enum |
| [Power Platform inventory API](https://learn.microsoft.com/en-us/power-platform/admin/inventory-api) | 요청·응답·위임 인증·페이지 |
| [Power Platform inventory](https://learn.microsoft.com/en-us/power-platform/admin/power-platform-inventory) | 지원 작성 도구·역할·SP 미지원 |
| [Copilot Studio inventory schema](https://learn.microsoft.com/en-us/microsoft-copilot-studio/admin-agent-inventory) | 필드·Agent Builder 예외·V1 제외·게시 구성·한계 |
| [Power Platform inventory schema](https://learn.microsoft.com/en-us/power-platform/admin/inventory-schema) | 최상위 `name`의 리소스 식별자 의미 |
| [Power Platform inventory sample queries](https://learn.microsoft.com/en-us/power-platform/admin/inventory-sample-queries#count-agents-by-harness) | `createdIn`의 `Microsoft 365 Copilot Agent Builder` 비교 예제 |
| [Copilot Studio Lite 학습 자료](https://microsoft.github.io/mcs-labs/labs/agent-builder-sharepoint/) | Lite 환경과 Agent Builder 작성 경험 |
| [ResourceQueryResponse.ResultTruncated](https://learn.microsoft.com/en-us/dotnet/api/microsoft.powerplatform.management.models.resourcequeryresponse.resulttruncated?view=power-platform-latest) | 정수 enum `0=잘림`, `1=잘림 아님` |
| [Agent Builder](https://learn.microsoft.com/en-us/plugins/agent-builder) | 작성·공유·라이선스 진입점 |

| 항목 | Azure 대상 | Copilot 대상 | 주의 |
| --- | --- | --- | --- |
| DS-SY-04 | 모델 배포 이름·버전·형식·업데이트 옵션 | 모델 선택 레이블·인식된 오케스트레이션 | 실제 기반 모델 버전·정책 승인 아님 |
| DS-SY-05 | 인바운드 경계 | 인증 사용·전체 테넌트 공유 제한 | 네트워크 격리·공개 채널 차단·공유 승인 아님 |
| DS-SY-06 | MCP 항상 실행 승인 | 활성 커넥터 사용자 동의 | 다른 통제이므로 동의를 실행별 승인으로 해석하지 않음 |
| BI-SY-09 | 완료 평가 보유 프로젝트 | Standard API 또는 실제 검토 화면에서 평가 기록을 확인한 Agent | 다른 하니스는 화면의 명시적 평가 없음만 반영. 새 평가 실행·품질 통과 아님 |
| BI-SY-10 | Healthy 보안 권고 | 인증·공유·제작자 자격 증명 위험 구성 3종 | 준비 상태 화면이나 스캔 성공·실제 방어 효과 아님 |
| BI-SY-12 | 버전·런타임·이미지 다이제스트 | 게시 시각 보유 | 게시 시각이 버전 고정·게시 승인 아님 |
| BI-SY-13 | Agent마다 소유자·스폰서·환경·비용센터 모두 확인 | Agent마다 소유자 존재 확인 | 조건이 다르므로 Copilot의 스폰서·비용 정보 보유를 뜻하지 않음 |
| DP-SY-15 | Agent와 실제 청사진의 정확 대조 | Copilot Studio의 실제 Agent ID·청사진 연결 | Agent Builder의 신원 필드 미적용은 제외 |
| OE-SY-19 | AI 계정·호스트의 관리 ID·직접 역할·키 인증 구성 | Agent마다 명시된 허용 인증 방식 확인 | 대상 단위와 조건이 다르며 실제 인증·권한 집행을 뜻하지 않음 |
| OE-SY-22 | 기존 리소스 지역·workspace 보존 기준 | 정확 연결된 관리 환경의 azureRegion | Copilot의 실제 처리 지역·M365 데이터 상주·로그 보존 준수 아님 |

플랫폼별 항목의 분자는 해당 조건을 충족한 대상 수이고 분모는 대상 수 합계입니다. 인벤토리 수집 미완료, 필수 값 미확인 또는 빈 전체 분모는 판정 보류입니다. 플랫폼별 조건과 대상 단위가 다르므로 동일한 정책 효과로 해석하지 않습니다. `authenticated_modes`·`orchestration_modes`는 구성 기준이며 조직의 정책 승인을 뜻하지 않습니다.

### 데모 Studio 초안 검증

| 구분 | 계약·한계 |
| --- | --- |
| CLI | [Copilot Studio CLI Preview](https://learn.microsoft.com/en-us/microsoft-365/copilot-managed-runtime/developer/agents/cli/) `0.2.128-beta`. 로컬 생성은 클라우드 생성이 아니며 배포와 게시를 구분 |
| 배포 응답 | `pushedComponentCount`는 설정·아이콘을 제외하므로 설정 전용 초안은 0개도 가능. 숫자만으로 성공을 판단하지 않음 |
| 실제 조회 | [Dataverse bot](https://learn.microsoft.com/en-us/power-apps/developer/data-platform/reference/entities/bot) `v9.2`의 `botid`, `schemaname`, `name`, `publishedon`. `publishedon`이 명시적 null일 때만 미게시로 확인 |
| 콘텐츠 | 로컬 합성 지침·제한 설정을 검사한 뒤 임시 복사본에서만 `agent pull` 실행. 클라우드 드리프트는 자동 덮어쓰지 않음 |
| 복구 | 정확한 클라우드 ID가 남은 실패 응답만 읽기 재검증. 당시 CLI 경고가 없으면 미확인으로 기록 |

### 선택 Agent 365 카탈로그

| 구분 | 계약 |
| --- | --- |
| API | `GET https://graph.microsoft.com/v1.0/copilot/admin/catalog/packages` |
| 실행 | `collect --agent365-registry` 또는 기술 설정 `agent365_registry: true`. 기본 비활성화 |
| 권한·라이선스 | `CopilotPackages.Read.All` 애플리케이션 권한·관리자 동의 및 Microsoft Agent 365 라이선스. E7에도 포함. 별도 승인 후 관리자 `setup.sh`의 `--agent365-reader`로 선택 부여 |
| 범위 | 기본 응답의 Agent 포함 패키지. 고유 Agent 수·독립된 공식 등록부·모든 초안의 목록과 다름 |
| 경계 | 별도 관리자 동의 필요. 진단 SP에 관리자 역할 부여 없음. 원본 콘텐츠·소유자 ID는 저장 전에 최소화 |
| 통합 | 기존 등록부 수집·페이지·교차검증에 연결. 26개 API 등급을 변경하지 않음 |
| 필드 불일치 | [copilotPackage 문서](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/admin-settings/package/resources/copilotpackage)는 `governanceMetadata`를 문자열(`PromptAgent`·`HostedAgent`·`WorkflowAgent`·`ManagedAgent`·`Unmanaged`·`AIApp`)로 명시하나 실제 v1.0 응답은 Foundry 패키지에서 `{"agenticType": "<값>"}` 객체를 반환(2026-11-19 관측). 키가 `agenticType` 하나이고 값이 문서의 열거값이면 그 값을 분류로 사용. 그 밖의 객체·형식은 원문 미저장·`null`/`error`로 기록하며 검증된 다른 필드와 완료된 목록은 유지 |
| 제약 | Global cloud 공식 지원. `--copilot-only`·fixture와 혼합해 실제 API에 접속하지 않음 |
| 공식 근거 | [List Copilot packages](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/admin-settings/package/copilotpackages-list), [Agent 365 라이선스](https://learn.microsoft.com/en-us/office365/servicedescriptions/microsoft-agent-365/microsoft-agent-365) |

#### Agent 365 경영진 보조 사용 지표 (2026-11-19 공식 문서 확인)

| 구분 | 읽기 계약·한계 |
| --- | --- |
| 공식 진입점 | [Agent 365 Graph API](https://learn.microsoft.com/en-us/microsoft-agent-365/admin/graph-api)는 패키지 목록·상세 API로 안내. 기존 `beta/agentRegistry/agentInstances`는 [통합·대체 안내](https://learn.microsoft.com/en-us/graph/api/agentregistry-list-agentinstances?view=graph-rest-beta)가 있어 호출하지 않음 |
| 추가 API | [Get package details](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/admin-settings/package/copilotpackagedetail-get) `GET /v1.0/copilot/admin/catalog/packages/{id}`. 기존 선택 옵션에서 완료된 목록의 패키지별로 GET만 수행하며 경로 ID를 URL 인코딩 |
| 버전·권한 | 목록·상세 모두 `v1.0`, Global cloud. 최소 권한 `CopilotPackages.Read.All`; 기존 DefaultAzureCredential·승인된 앱 권한 재사용. API 개요의 AI 관리자·전역 관리자 안내를 진단 SP에 디렉터리 관리자 역할을 주라는 뜻으로 확대하지 않음 |
| 라이선스 | API 자체에 Microsoft Agent 365 라이선스 필요(독립 구독 또는 E7 포함). 관리 센터 기본 인벤토리와 Graph API 라이선스는 다르며 GCC 관리 센터 지원을 이 API 지원으로 추론하지 않음 |
| 사용 지표 | [copilotPackageDetail](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/admin-settings/package/resources/copilotpackagedetail)의 최근 30일 값을 저장: `activeUsers`→`active_users_30d`(패키지 간 중복 사용자가 있어 합계를 고유 사용자 수로 쓰지 않음), `totalSessions`→`total_sessions_30d`, `totalRunTimeInHours`→`total_run_time_hours_30d`(호출 수·토큰·비용·가용률로 변환하지 않음), `exceptionRate`→`exception_count_30d`(이름과 달리 공식 설명이 '예외 수'인 Double이며 백분율·오류율·SLA로 해석하지 않음), `lastUsedDateTime`→시간대 있는 `last_used_at`(미제공은 미확인이며 장기 미사용·폐기 승인의 증거가 아님) |
| 검증·부분 실패 | Int32 비음수 정수·유한 비음수 Double·시간대 있는 날짜만 허용. 누락은 `null/not_found`, 형식 오류는 해당 필드만 `null/error`. 상세 ID·확인된 버전이 목록과 다르면 연결하지 않으며 다른 패키지·완료된 목록은 유지 |
| 완료·실패 | 패키지 `detail_complete`는 5개 추가 필드가 모두 검증된 경우만 true. `agent365_details_complete`는 목록 완료 및 모든 패키지 상세 필드 검증 여부이며 모집단·관측기간 완전성을 뜻하지 않음. 빈 목록에는 지표·분모를 만들지 않음. 상세 실패는 `agent365_package_details` 이슈와 필드별 표준 사유로 남김 |
| 증적·PII | 기존 목록 증적과 별도의 `detail_evidence_refs`에 패키지 ID·수치·날짜·필드 사유와 아래 허용 메타데이터만 저장. 사용자·그룹·연락처·요청자·소유자 ID·설명·본문·원본 오류는 저장하지 않으며 원본 자동 저장이 없는 HTTP 클라이언트만 사용 |
| API 제약 | 상세 `version` 쿼리와 `$select=id,requestMetadata`는 확인 문서에서 beta 전용이므로 v1.0에 추가하지 않음. 사용 지표를 특정 Azure 배포 버전에 귀속하지 않음 |
| 미구현 범위 | beta 요청 메타데이터·정책 템플릿은 개인정보 및 preview 계약을 포함하므로 미수집. 기본 Agent 목록으로 전체 MCP·skill·커넥터 수를 추정하지 않음 |
| 실패 해석·평가 경계 | 명시적 `not licensed` 오류만 `license_missing`, 일반 403은 `permission_denied`. 기능 미지원·조회 오류·필수 필드 부재·빈 분모는 0이나 L1로 치환하지 않음. 추가 필드는 보조 인사이트이며 26개 API 등급·관리자 읽기 3개·Defender 플랜 항목의 의미·분모를 변경하지 않음 |

#### Agent 365 안전한 분류 메타데이터 (2026-11-19 공식 문서 확인)

| 공식 필드·모델 | 수집·경영진 해석 한계 |
| --- | --- |
| 근거·요청 | [v1.0 상세 속성](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/admin-settings/package/resources/copilotpackagedetail), [상속 기본 속성·packageType](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/admin-settings/package/resources/copilotpackage), [목록의 호스트·요소 예시](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/admin-settings/package/copilotpackages-list). 기존 목록·상세 GET 응답만 재사용하며 요청·권한 추가 없음 |
| `type` → `package_type` | 공식 enum `microsoft/external/shared/custom`만 원문 보존. 공급·공유 유형 분류용이며 공급자 신뢰·보안 승인·내부 소유권을 증명하지 않음. `unknownFutureValue`와 미확인 값은 null·사유 |
| `manifestVersion` → `manifest_version` | 매니페스트 스키마 버전. 개인정보 최소화를 위한 로컬 필터로 최대 32자의 2~4개 숫자 세그먼트만 저장. API의 전체 버전 문법이라고 주장하지 않으며 다른 문자열은 null·사유. 패키지·호스트 런타임·Azure 모델 버전과 별개 |
| `appId` → `app_id` | 공식 Entra 애플리케이션 등록 ID만 UUID 형식으로 검증·보존. 사용자 ID·클라이언트 비밀·Agent ID가 아니며 추가 신원 조회·권한 대사에 사용하지 않음 |
| `supportedHosts` → `supported_hosts` | 사용 가능한 호스트 앱 이름의 문자열 배열. 공식 예시의 Teams·Outlook·SharePoint·Word·Excel·PowerPoint·Copilot·M365만 대소문자 의미 변환 없이 원문 표기로 보존. 실제 설치·배포·호출·허용 사용자를 의미하지 않음 |
| `elementTypes` → `element_types` | 패키지 포함 요소 종류의 문자열 배열. 공식 예시·지원 값에 포함된 bot/Bots, declarativeAgent, CustomEngineAgent, officeAddIn(s), AgentConnectors, AgentSkills, DeclarativeCopilots, CustomEngineCopilots만 원문 표기로 보존. 별칭을 다른 값으로 변환하지 않으며 도구 정의·URL·지침은 수집하지 않음 |
| `categories` → `categories`, `category_count` | 공식 속성은 기능·도메인 분류용 자유 문자열 배열이며 전체 enum이 아님. 개인정보가 들어갈 수 있어 문서 예시 Development·Productivity·Tools만 이름 보존. 그 밖의 분류가 섞이면 배열 전체는 null·사유로 두고 유효한 문자열 배열의 항목 개수만 `category_count`에 저장 |
| `sensitivity` → `sensitivity`, `sensitivity_present` | 공식 속성은 패키지의 데이터 취급·준수 제한 관련 문자열 분류이며 enum은 미제공. [상세 GET의 예시](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/admin-settings/package/copilotpackagedetail-get)의 `general`만 문자열로 보존. 그 밖에는 분류 문자열 null·사유 및 비어 있지 않은 문자열의 존재 여부만 true로 기록. Purview 민감도 레이블 적용·유효성·DLP 집행 증거로 해석하지 않음 |
| 로컬 안전 필터 | 위 허용 목록은 API enum 전체가 아니라 원문 저장을 제한하는 로컬 개인정보 보호 규칙. 배열은 최대 64항목이며 초과 시 배열 전체를 null로 두고 유효한 categories 항목 개수만 유지. 미확인 문자열은 해시·별칭·잘라낸 본문으로도 저장하지 않고 `null/feature_unavailable`로 기록. 형식 불일치는 해당 필드만 `null/error`, 누락·빈 문자열은 `null/not_found` |
| 빈 배열·파생 값 | 명시적 빈 배열은 `[]`, 분류 항목 수는 0으로 보존하되 평가 분모·성숙도 점수가 아님. 미제공·잘못된 배열은 `null`과 사유. 민감도 문자열 미확인은 false가 아닌 null |
| 원천·연결 | 기본 5필드(type/manifestVersion/appId/supportedHosts/elementTypes)는 목록부터 보존. 상세에 명시적 필드가 있으면 상세 값을 사용하며 명시적 null은 목록 값으로 메우지 않음. 상세에 키 자체가 없으면 목록 값 유지. categories/sensitivity는 상세 속성에서만 읽음 |
| 증적 추적 | `metadata_field_sources`는 catalog/detail/not_requested, `metadata_evidence_refs[field]`는 해당 필드의 최소화 증적. 원본 JSON의 `metadata` projection에 검증 값·사유·원천 보존. 상세 실패에도 확인된 목록 값은 유지 |
| 완료·구버전 | `metadata_complete`는 원문 7필드가 모두 검증된 경우만 true. `detail_complete`의 30일 사용 지표 5필드 의미는 변경하지 않음. 구버전 결과의 새 필드는 null·not_found이며 보고서 재패키징만으로 복원할 수 없어 승인된 실제 재수집이 필요 |
| 범위 | 기존 26개 등급·교차검증·Azure/Copilot 분모는 변경하지 않음. 도구까지 포함한 전체 인벤토리·승인 현황·위험도 또는 과거 30일 이력을 추정하지 않음 |

| 저장 위치·보고서 지표 연동 | 현재 상태·안전한 표시 |
| --- | --- |
| 저장·키 | Collection의 `agent365_packages`·raw JSON·마스킹 증적과 Excel 8번 Raw에 보존. PPT 보고서 지표의 `catalog.package.<순번>.metadata.<field>` 키에 연결하며 원천이 기록되면 `.source` 키도 제공. 필드는 `package_type`, `manifest_version`, `app_id`, `supported_hosts`, `element_types`, `categories`, `category_count`, `sensitivity`, `sensitivity_present`이며 `metadata_complete`는 수집 완전성 플래그일 뿐 평가 지표가 아님 |
| 표시 조건 | `field_status[field]`의 null·사유를 우선하고 `catalog` 또는 `detail` 원천과 필드 증적이 있는 값만 표시. 동일 package_id 중복은 null/error로 보류. 누락은 not_found, 형식 불일치는 error, 로컬 안전 필터 미확인은 feature_unavailable, 미조회는 not_found 및 not_requested. `metadata_complete=false`만으로 확인된 값을 버리지 않음 |
| 목록·bool 표시 | 확인된 배열은 JSON 문자열로 표시하며 `[]`는 확인된 빈 배열로 null과 구분. `sensitivity_present=true`는 '분류 문자열 존재'로만 표시 |
| 집계 단위 | 유형·호스트·요소·분류별 건수는 해당 필드가 확인된 카탈로그 패키지 기준이며 고유 Agent 수·전사 고유 사용자 수로 부르거나 합산하지 않음. 전체 분포는 목록 완료·해당 필드 전체 확인 시에만 확정하고 일부 미확인이면 부분 관측으로 명시하며 전체 비율·빈 분모는 null. 메타데이터는 현재 구성 스냅샷이며 30일 사용 지표와 기간을 혼합하지 않음 |
| 증적 연결 | 필드별 `metadata_evidence_refs[field]`와 `metadata_field_sources[field]`를 연결. 전체 패키지의 참조를 단일 셀에 합치지 말고 증적별 행·참조색인을 사용하여 Excel 32,767자 한도를 지킴 |

| 435~436개 패키지 재수집 보호 | 동작·해석 |
| --- | --- |
| 요청 규모 | 패키지 435~436개이면 순차 상세 GET 435~436건과 목록 페이지 조회(고정 제한 아님). 별도 스레드·`$batch`·반복 폴링 없음. HTTP 클라이언트는 요청당 최대 4회 시도하므로 보호가 없으면 상세만 최대 1,744회가 될 수 있음 |
| 429·일시 오류 | [공식 Graph 지침](https://learn.microsoft.com/en-us/graph/throttling)에 따라 숫자 `Retry-After` 대기, 헤더 부재 시 지수 백오프. 상세의 재시도 소진 429/5xx, 60초 초과 서버 대기 지시, 비숫자 `Retry-After`는 남은 상세 전체 중단 |
| 시간·연속 실패 | 상세 단계 시작 후 600초 이상이면 새 패키지 요청을 시작하지 않음(진행 중 요청은 완료될 수 있으며 HTTP 연결/읽기 제한은 10/60초이므로 실제 경과시간을 별도 기록). 요청·ID/버전 검증 연속 5건 실패 시 나머지 상세 중단. 성공 응답은 연속 실패를 초기화하며 필드 누락·일부 형식 오류만으로 다른 패키지를 차단하지 않음 |
| 부분 실패 | `facts.agent365_detail_collection`에 후보·시도·요청 실패·5필드 완료·필드 미완료(`partial_packages`)·미조회 패키지 수, 중단 원인·경과시간 보존. 중단 전 확인 값·전체 목록은 유지. 보호 중단 후 대상은 `null/not_found`와 미조회 사유이며 첫 패키지의 권한·라이선스 실패를 나머지에 전파하지 않고 하나의 최소 로컬 요약 증적을 공유 |
| 기간·개인정보 | 공식 설명은 최근 30일이나 원천 집계 시작·종료 시각·공통 기준 시각을 제공하지 않으므로 `usage_window_days=30`, `source_period_start/end=null`로 보존하며 순차 수집을 같은 시점의 스냅샷으로 표시하지 않음. 상세 증적은 수치·기술 ID·날짜만 허용하고 소규모 집계 비식별 보장은 확인하지 못했으므로 '완전 익명'이라 표시하지 않으며 로컬 집계 증적도 접근 통제 대상 |

### 통합 Excel 템플릿

| 계약 | 내용 |
| --- | --- |
| 기본 파일 | `assessment-result-template.xlsx`는 원본 통합 14개 시트·폰트·크기를 유지. SY는 `criteria.yaml`의 26개 코드·정의·분모·5단계 조건 사용 |
| 자동 입력 | `2_SE 원천데이터` F5:F56에 항목별 측정값. 노란 입력 셀·한글 단위를 유지하고 데이터 유효성 검사는 제거. 미확인·실패·빈 분모는 공란과 사유 보존 |
| 추출 표시 | I열은 `yyyy-mm-dd hh:mm:ss KST`, J열은 `EASM 자동화 모듈`. K열은 간단한 비고이며 상세 근거·증적은 주석·근거 시트에 보존 |
| 입력 항목 표시 | E열(입력 항목)은 D열(수집 항목, 큰 분류)에 속한 구체적 작은 분류입니다. 항목별 `criteria.yaml`의 `numerator`·`denominator` 문구를 그대로 사용하며 "기준 충족 수"·"측정 대상 수" 같은 공통 문구로 대체하지 않습니다 |
| 원천데이터 UI | 코드별 2행(충족·분모) 끝에 굵은 경계선을 표시해 항목 구분을 명확히 합니다. I·J·K열은 왼쪽 정렬이며 열 너비·행 높이는 실제 내용이 한 줄로 보이도록 고정합니다 |
| 표시·원본 분리 | 숨김 L열은 원본 UTC 수집 시각, M/N열은 기계 판독용 단위·통화. KST 표시나 한글 단위 때문에 Excel 단독 PPT 변환의 시각·통화가 바뀌지 않음 |
| 판정·출처 | `3_SE 판정`은 수집 당시 등급과 기준 사본을 반영. 숨김 U:Y열은 저장 API 등급·충족률·상태·사유·조치이며, 헤드리스 PPT 생성은 이 관측값을 읽음. 수식 캐시는 I/K열에 동일 등급 기록 |
| 수동 입력 | 54문항·문서·인용과 제공된 값을 보존. `--interview-workbook`으로 원본 지정. 수동 입력은 API가 확인·승인한 결과가 아님 |
| 집계 | 환경·리소스·Agent ID·금액 분모를 전사 Agent 커버리지로 합산하지 않음 |
| 세부 표 | `2b` 표3은 명시적 게시 시각·채널로 Copilot을 중복 없이 분류. 표4는 기존 BI-SY-13·OE-SY-19·DS-SY-05·BI-SY-10 대상별 판정의 Copilot 부분만 표시. 표4 합계에는 같은 Agent가 여러 번 포함됨. 사용 90일·민감 데이터 노출·조치율로 대체 해석 금지 |
| 수집 방식 | A는 프로그램의 공식 API 읽기이며 승인된 위임 사용자 API 내보내기도 포함. E는 실제 관리 화면 또는 수동 내보내기 증적. 파일 전달 여부가 아닌 실제 원천으로 구분. API 원천의 오래된 관측을 새 조회라고 표시하지 않음 |
| 7번 열·표시 | 상단 단계 점수와 15행 이하 페이지 대응표의 열 의미가 다름. 고정·반복 인쇄는 제목 1~2행만 사용. 건수에 % 서식을 상속하지 않으며 텍스트화된 시각 참조를 실제 수식으로 기록. 전 행 높이 24pt |
| Excel 색상 | 같은 표의 입력·참조 값 열은 빈 셀·수식을 포함해 노란 바탕·파란 글자로 통일. 추가 원천 데이터 표는 흰 바탕·검정 글자로 표시하며 교대 행 채우기는 사용하지 않음. 헤더·합계·판정 조건부 서식은 유지 |
| 7번 보정 | G5:G10만 보정 여부이며 15행 이후 G열은 보고서 표기. 판정 행 97~122는 등급·충족률, 원천 행 134~159는 실제 분자·분모를 표시하고 서로의 원천 셀을 혼용하지 않음 |
| 보고서 매핑 | `7`의 26개 항목 모두 장표·분류·최신 명칭·원천 셀을 표시. `7a`의 전체 범위는 26행이며 코드별 경계선을 적용. III 표는 범위가 부족한 항목만 표시하며 모두 확인됐으면 빈 목록이 정상 |
| 숨김 보조 열 | 매트릭스 Z열은 원래의 코드·항목 표시 수식. 자동으로 생성된 E 표기의 재사용 방지 정보는 별도 AA열에 보존하여 범위 시트의 Z열 참조와 충돌하지 않게 함 |
| 플랫폼별 분해 | Power Platform 환경 항목은 P1·P2 공통 측정. Copilot 확장 항목은 해당 Agent의 대상별 판정만 분해하며 Azure 수를 Copilot에 복제하지 않음. Graph Agent ID는 실제 귀속 기준. Agent Builder 신원 필드 미적용은 제외. P4~P7은 현재 수집기 진단 범위 밖이며 제품 전체의 Agent ID 미지원으로 단정하지 않음 |
| 호환성 | 새 보고서는 14개 시트 뒤에 감사·Raw 4개 시트 추가. 과거 보고서의 `6. 수집 결과` 입력도 읽기·PPT 재생성 지원. 실제 수집값·로컬 식별자를 기본 템플릿에 포함하지 않음 |
| 수식 재계산 | 수집값을 넣으면 Excel이 집계 수식을 재계산. PPT는 Excel 실행 없이 저장 API 등급과 수동 응답·증적 상한으로 계산. 미입력 응답을 0점으로 바꾸지 않음 |

### 원본 PPT의 추가 증적과 한계

| 원본 요구 지표 | 현재 처리 |
| --- | --- |
| 생성 승인·독립 등록부 | `DM-SY-27`, `DP-SY-28`: 승인 워크플로·조직 등록부의 명시적 ID·시간을 승인 파일로 대사. 배포 승인·서비스 카탈로그로 대체하지 않음 |
| 배포 전 완료 평가 | `BI-SY-29`: 동일 버전·완료 시각·배포 시각의 대사. 평가 실행 생성 시각으로 대체하지 않음 |
| 조건부 접근 | `OE-SY-30`: 별도 관리자 읽기 내보내기의 명시적 Agent ID 대상. 미확인 선택자·속성 필터는 보류 |
| 사용자 지정 감사 보존 | `OE-SY-31`: 실제 정책 enum·우선순위. 월 단위 최소 구성만 표시하며 실제 보존이 아님 |
| 90일 미사용 | `OT-SY-32`: Agent 단위 전체 관측 구간·30/90일 호출 수. 짧은 로그 구간으로 미사용을 단정하지 않음 |
| 고위험 노출 조치 | `OT-SY-33`: 승인된 발견·심각도·조치 상태 내보내기. Defender 플랜·단순 경보 종료와 다름 |
| 월별 실제 비용 | `OT-SY-34`: `--report-cost-history`로 현재 발견된 Azure AI 리소스의 기간별 비용 조회. 삭제 리소스·과거 Agent 귀속·M365 청구는 제외. 검증된 기간별 귀속 기록도 승인 파일로 수용 |
| Copilot 구성 | `DP-SY-35`, `DS-SY-36`, `OE-SY-37`: 공식 인벤토리의 게시 시각·인증 방식·소유자 존재. 독립된 보안 평가가 아님 |
| 패키지 게시 요청 | `DP-SY-38`: 카탈로그 `requestType=publish`의 반환된 승인 상태. Agent 생성 업무 승인이 아님 |
| 소유자 퇴사 대사 | `OE-SY-39`: 승인된 인사 대사 결과의 Agent ID·nullable bool만 사용. 인사 원본·사용자 ID·이름은 입력하지 않음. 계정 비활성은 퇴사 증거가 아님 |
| PPT 렌더링 | 원본 27장의 설명·제언·인터뷰와 테마·배경·미디어를 보존. SY 26개 표는 14행 × 6열. 미확보 실측·해당 예시 막대만 확인 중 처리 |

추가 SY의 명칭·지표·기간·보고서 검토 목표는 `config/criteria.yaml`의 `report_items`·`report_options`를 수집 당시 기준 사본에 보존합니다. **기존 26개 API 등급에는 합산하지 않습니다.** Excel 7번의 별도 표·8번 Raw에서 값·분모·원천·한계를 추적하며 월별 차트는 최근 최대 6개 월만 표시합니다.

| 원천·계약 | 공식 근거·해석 한계 |
| --- | --- |
| CA 정책 읽기 | `GET /beta/identity/conditionalAccess/policies`. [목록·권한](https://learn.microsoft.com/en-us/graph/api/conditionalaccessroot-list-policies?view=graph-rest-beta), [대상 스키마](https://learn.microsoft.com/en-us/graph/api/resources/conditionalaccessclientapplications?view=graph-rest-beta). `Policy.Read.All` 및 읽기 사용자 역할과 Agent ID 목록 읽기 권한 필요. 진단 SP에 관리자 역할을 추가하지 않음 |
| CA 대상 계산 | `enabled`와 명시적 `includeAgentIdServicePrincipals` ID·제외 ID만 대사. `All`·속성 필터·일반 서비스 주체 선택자의 Agent 적용 의미는 미확인. 보고 전용은 집행 구성으로 세지 않으며 실제 토큰 집행의 증명이 아님 |
| Foundry 평가 | [실행 조회](https://learn.microsoft.com/en-us/azure/foundry/reference/rest/evals-get-eval-run)의 `created_at`은 생성 시각이며 `modified_at`은 완료 시각 정의가 없음. 실제 배포 기록의 별도 완료 시각 필요 |
| Purview 정책 | [Get-UnifiedAuditLogRetentionPolicy](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/get-unifiedauditlogretentionpolicy?view=exchange-ps). `ThreeMonths/SixMonths/NineMonths/TwelveMonths/TenYears`를 3/6/9/12/120개월로 표시하며 일수로 변환하지 않음. 사용자 지정 정책만 수용 |
| 카탈로그 확장 | [copilotPackage](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/admin-settings/package/resources/copilotpackage)의 `manifestId`, `lastModifiedDateTime`, `requestType` 추가 수집. 미확인 미래 enum은 0으로 치환하지 않음 |
| 게시 시각 null | [인벤토리 스키마](https://learn.microsoft.com/en-us/microsoft-copilot-studio/admin-agent-inventory)는 `lastPublishedAt` null을 초안으로 정의. 게시 시각 보유 여부에만 사용하며 채널 가동·응답을 추론하지 않음 |

#### 승인된 추가 증적 파일

| 필드 | 계약 |
| --- | --- |
| 봉투 | `schema_version=1`, `source_type=approved_report_evidence`, `approved=true`, `tenant_id`, `tenant_verified`, `data_mode=live`, `exported_at`, `datasets` |
| 데이터셋 | 코드·`kind`·`scope`·`source_kind`·기술적 `source_ref`·`observed_at`·`complete`·`population_complete`·`reason`·`records`. 시계열에는 시간대가 있는 `period_start/end` 필요 |
| 대상·개인정보 | `subject`는 기술 ID. 이름·인사 원문·대화·민감 정보 본문을 넣지 않고 발견 유형과 상태만 입력 |
| 실패 | 미완료는 `complete=false`와 표준 사유. 필수 값 미확인·빈 분모·전체 모집단 미확인은 null. 파일 내 중복 코드·ID·미래 시각·기간 불일치 거부 |
| 신뢰 | 승인 표시·테넌트 일치·최근 24시간·스키마·시간 검증 후 마스킹 저장. 파일 해시는 원천 인증 서명이 아님 |
| 재패키징 | 새 증적 첨부에는 `package --reassess`와 명시적 테넌트 필요 |

```powershell
# 전체 데이터셋의 정확한 필드·필수 값·nullable·enum 확인 - API 호출 없음
python scripts\export_report_evidence.py --schema > report-evidence-schema.json

# 별도 승인된 읽기 사용자로 실행 - 자동 로그인·권한 변경 없음
python scripts\export_report_evidence.py --conditional-access --approved --tenant-id "<테넌트 ID>" --output conditional-access.json

# Azure Reader 수집에 추가 - 승인·등록부·사용·노출 등의 파일도 같은 옵션으로 반복 지정
easm-agent collect --setup-file .easm-agent\setup.json --report-cost-history --report-evidence-file conditional-access.json
```

수집 불가한 업무·인사·DSPM·과거 이력을 데모 배포 영수증으로 만들어 채우지 않습니다. 원천이 제공되지 않으면 PPT의 해당 값도 보류합니다.

| 재현성 규칙 | 처리 |
| --- | --- |
| 해시 | 기준 JSON은 UTF-8·키 정렬·공백 없이 직렬화한 SHA256. 소스는 Python 파일별 SHA256 목록을 같은 방식으로 해시. 원천 서명·배포 승인은 아님 |
| 과거 결과 | 당시 사본이 없으면 현재 기준으로 채우지 않음 |
| `package` | 저장 판정·기준 사본 유지. 새 기준·관리자 증적의 판정 반영은 `--reassess` 필요 |
| 재평가 | 원래 수집 시각 유지. `origin=saved_snapshot_reassessment`·재평가 시각·원본 데이터 SHA256 기록 |
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
| 고객 입력 | `policy_facts`, 외부 승인, `major_type_blueprints_defined`, 허용 모델·내부 기준 등 과거 Settings 필드는 기존 로컬 설정 로딩 호환용이며 등급에 사용하지 않음 |
| 해석 한계 | L4/L5도 API 구성·기록의 비율이며 정책의 승인·실효성·자동화 동작·개선 효과를 설정만으로 추론하지 않음 |
| 기준 변경 | 지표·임계값·기간은 `criteria.yaml`, 수집 기술 설정은 선택 `custom-config.yaml`. `--criteria`로 별도 기준 지정. 설치본 기본 기준도 패키지에 포함 |
| 범위 | `partial` 결과는 명시된 Azure 부분 범위의 지표이며 조직 전체 통제 충족을 의미하지 않음 |

### 26개 API 지표

| 코드·현재 명칭 | 분모 | 충족 API 증거 | 해석 한계 |
| --- | --- | --- | --- |
| DM-SY-01 Power Platform 환경 역할 할당 | 관리자에게 보이는 환경 수 | 환경별 역할 할당 건수 1 이상(`Get-AdminPowerAppEnvironmentRoleAssignment`) | [공식 명령](https://learn.microsoft.com/en-us/powershell/module/microsoft.powerapps.administration.powershell/get-adminpowerappenvironmentroleassignment?view=pa-ps-latest)은 비 Dataverse 환경만 반환하므로 Dataverse 환경은 관리자가 `scripts\export_dataverse_roles.py`로 별도 내보낸 `powerplatform.dataverse_roles`(`systemusers`의 System Administrator 또는 Environment Maker 역할을 가진 사용 설정 대화형 사용자 건수, 사용자·역할 이름 미내보내기)로 보완. 두 원천 중 명령 결과를 우선. 건수 미확인 환경은 0이 아닌 판정 보류. 고유 제작자 수·전체 유효 권한 아님 |
| DS-SY-02 데이터 정책 환경 적용 | 관리자에게 보이는 환경 수 | DLP 정책 `FilterType`·`Environments`로 환경이 범위에 포함(전체·포함·제외 해석) | 커넥터 분류·차단 효과 아님. 정책이 없으면 0% |
| BI-SY-08 관리형 환경 보호 수준 | 관리자에게 보이는 환경 수 | 환경 `protectionLevel=Standard` | `Standard`=관리형 환경은 필드 값에 근거한 해석. 환경 분리 실효성 아님 |
| DS-SY-03 Agent ID의 Blueprint 연결 | Graph Agent ID 수 | `applications/microsoft.graph.agentIdentityBlueprint`와 `servicePrincipals/microsoft.graph.agentIdentity`의 `agentIdentityBlueprintId` 대조 | Blueprint 조직 표준 승인·업무 유형 분류 아님 |
| DS-SY-04 플랫폼별 모델·오케스트레이션 구성 | Azure 모델 배포 및 Copilot Agent 수 | Azure 모델·버전·형식·업데이트 옵션 또는 Copilot 모델 레이블·인식된 오케스트레이션 | 조건이 다름. 실제 기반 모델 버전·허용 모델 승인·퇴역 대응 아님 |
| DS-SY-05 플랫폼별 접근 범위 구성 | AI 계정·호스트 및 Copilot Agent 수 | Azure 인바운드 경계 또는 Copilot 인증 사용·전체 테넌트 공유 제한 | Copilot 공유 제한이 네트워크 격리·공개 채널 차단·공유 승인 아님 |
| DS-SY-06 도구 승인·사용자 동의 구성 | MCP 도구 및 활성 Copilot 커넥터 작업 수 | MCP require_approval=always 또는 Copilot requiresEndUserConsent=true | 다른 통제. 비활성·함수·내장 도구 제외. 200개 제한·건수 불일치·필수 값 미확인은 보류 |
| DS-SY-07 외부 도구 HTTPS 연결 구성 | 명시적 외부 도구 URL 수 | `server_url·url`의 HTTPS scheme·유효 hostname·userinfo 부재 | 업무 승인·상대 서버 신뢰·인증 성공 아님. 경로·쿼리·인증값 미저장 |
| BI-SY-09 플랫폼별 완료 평가 실행 기록 | Foundry 프로젝트 및 평가 기록 확인 Copilot Agent 수 | Foundry 완료 평가, Standard Copilot GET의 Completed·endTime 또는 실제 화면 No evaluation run | 다른 하니스는 화면의 평가 없음만 포함. 작성 화면은 게시 버전 평가·품질 통과 증명 아님 |
| BI-SY-10 플랫폼별 보안 점검 상태 | 적용 가능한 AI 보안 권고 및 Copilot Agent 수 | Azure Healthy 권고 또는 Copilot 인증·공유·제작자 자격 증명 위험 구성 3종 | Azure 권고 없음은 준수 아님. Copilot 준비 상태·스캔 성공·방어 효과를 추론하지 않음 |
| BI-SY-11 콘텐츠 필터 정책 연결 | 모델 배포 수 | 배포 `raiPolicyName`으로 연결된 실제 `accounts/raiPolicies`를 식별하고 `contentFilters.enabled` 확인 | 필터 값 미확인은 null. 실제 차단 효과·강도 승인 아님. 정책명만으로 충족하지 않음 |
| BI-SY-12 플랫폼별 Agent 버전·게시 기록 | Foundry Agent·자체 호스트 및 Copilot Agent 수 | Azure 버전·런타임·이미지 다이제스트 또는 Copilot lastPublishedAt | 게시 시각은 버전 고정·승인·롤백 기록 아님. 초안의 미게시를 안전성 실패로 해석하지 않음 |
| BI-SY-13 플랫폼별 Agent 책임·자산 메타데이터 | Azure 및 Copilot Agent 수 | Azure의 owner·sponsor·env·cost-center, Copilot의 소유자 존재 | 플랫폼별 조건이 다르며 업무 승인·인사 상태 아님 |
| BI-SY-14 AI 리소스 정책 평가 준수 | 정책 평가가 있는 AI 관련 리소스 수 | `PolicyResources` policyStates를 리소스별 대조해 모든 평가가 `Compliant` | `Exempt·Unknown`·평가 없음은 준수 아님. 자동 교정 효과 아님 |
| DP-SY-15 플랫폼별 Agent ID·청사진 연결 | Azure 및 Copilot Studio Agent 수 | Azure Agent·청사진 정확 대조 또는 Copilot ID의 실제 Graph Agent ID·청사진 연결 | Agent Builder 신원 필드 미적용은 제외. 관리 ID·패키지 목록으로 대체하지 않음 |
| OE-SY-16 Agent ID 소유자·스폰서 연결 | Graph Agent ID 수 | 실제 `owners` 수 > 0 및 `sponsors` 수 > 0 | 기본 Graph 읽기 권한의 사용자 속성 제한 때문에 accountEnabled는 조건에서 제외. 계정 활성 상태·퇴사자 판정·인사 대사 아님. 이름·UPN 미저장 |
| OE-SY-17 Agent ID 앱 역할 읽기 범위 | Graph Agent ID 수 | `appRoleAssignments`와 대상 SP의 `appRoles.value`를 해석해 기준의 쓰기·전체제어 패턴 앱 역할 없음 | ARM·위임·앱 내부 권한 제외 |
| OE-SY-18 Agent 리소스 실행 로그 연결 | AI 계정·자체 Agent 호스트 수 | `diagnosticSettings.logs.enabled`와 `workspaceId` 연결 | 구독 공통 Activity Log 제외. 이벤트 유입·테이블 유효 보존기간 아님 |
| OE-SY-19 플랫폼별 인증·권한 구성 | AI 계정·자체 Agent 호스트 및 Copilot Agent 수 | Azure 관리 ID·직접 역할·키 설정 또는 Copilot 인증 방식 | 플랫폼별 조건·단위가 다르며 실제 인증 사용 제외 |
| OE-SY-20 AI 리소스 활성 경보 범위 | AI 계정·자체 Agent 호스트 수 | `metricAlerts·scheduledQueryRules·activityLogAlerts`의 enabled·scopes를 실제 AI 리소스 ID에 대조 | 경보 발생·SLO 충족·trace 유입 아님 |
| OE-SY-21 AI 경보의 작업 그룹·수신자 연결 | AI 대상 경보 수 | 활성 경보의 actionGroupId·actionGroups에 존재하는 작업 그룹과 활성 email·SMS·webhook·armRole·Function·LogicApp·ITSM receivers 연결 | 실제 전달 성공·온콜 대응 시간·복구 시험 아님. 주소·이름 미저장 |
| OE-SY-22 플랫폼별 지역·보존 구성 정보 | AI 계정·호스트 및 Copilot Agent 수 | Azure 지역·보존 조건 또는 Copilot environmentId에 정확 연결한 관리자 환경의 azureRegion | Copilot은 관리 환경 지역만 확인. 실제 모델·M365 처리 지역·로그 보존 준수·법적 삭제 아님 |
| OT-SY-23 AI 리소스 사용량 관측 범위 | AI 계정·자체 Agent 호스트 수 | `metricDefinitions`와 `metrics.timeseries.data`에 기간 내 숫자 표본, 기본 30일 | 숫자 0도 관측됨. Agent별 사용자 수·90일 미사용 여부 아님 |
| OT-SY-24 AI 비용의 단일 Agent 귀속 | 동일 통화의 양수 AI 비용 금액 | Daily query의 ResourceId·UsageDate·Cost·Currency와 Agent·모델·호스트·플랜 ID 대조. 일자 존재·단일 Agent 귀속 금액, 기본 30일 | 공유 비용 중복 배분 금지. 통화 혼재·음수 조정·분모 0은 산출하지 않음 |
| OT-SY-25 AI 민감 데이터 노출 점검 구성 | 승인 구독 수 | `Microsoft.Security/pricings`(2024-01-01)의 `AI` 플랜 `pricingTier=Standard`, `CloudPosture` 플랜 `Standard`와 `SensitiveDataDiscovery` 확장 `isEnabled=True`를 모두 충족. `AIPromptEvidence`·`AIModelScanner` 확장은 상태만 기록 | 플랜·확장 구성이며 실제 경보 발생·민감 데이터 노출·조치 완료 아님. 구독 안 모든 AI 리소스 적용 범위 미확인. 필드 누락은 `null` |
| OT-SY-26 구독 예산·실제·예측 경보 구성 | 승인 구독 수 | 현재 유효한 양수·무필터 `Cost` 예산과 활성 Actual·Forecasted 임계값 경보·수신자 존재 | Agent별 예산·실제 전달 성공·통보 후 자동 조치 아님 |

- DS-SY-04의 업데이트 옵션은 `NoAutoUpgrade`, `OnceNewDefaultVersionAvailable`, `OnceCurrentVersionExpired`이며 어느 옵션도 모델 승인이나 퇴역 대응을 보장하지 않습니다.
- OE-SY-17의 기본 패턴은 `*.ReadWrite.All`, `*.Write.All`, `*FullControl*`이며 `criteria.yaml`에서 관리합니다. 매칭되지 않는 역할을 최소 권한 인증으로 해석하지 않습니다.
- 기본 기간은 OE-SY-22 `workspace_retention_target_days: 90`, OT-SY-23 `usage_window_days: 30`, OT-SY-24 `cost_window_days: 30`입니다. workspace 설정값은 테이블별 유효 보존기간이 아닙니다.
- OT-SY-26은 `amount·category·timePeriod·filter`, 활성 notifications의 `thresholdType·threshold`와 수신자 존재를 함께 확인합니다. 만료·향후·필터 예산 또는 예측 경보만 있는 예산을 구독 전체 충족으로 보지 않습니다.
- OT-SY-25은 진단 SP의 Security Reader로 `Microsoft.Security/pricings`를 읽습니다. AI 또는 CloudPosture 플랜이 없거나 필드를 확인하지 못한 구독이 있으면 `null`과 사유를 유지하고 L1로 대체하지 않습니다. 공식 근거: [AI 서비스 위협 방지 활성화](https://learn.microsoft.com/en-us/azure/defender-for-cloud/ai-onboarding), [AI 보안 상태 관리](https://learn.microsoft.com/en-us/azure/defender-for-cloud/ai-security-posture), [Pricings REST API](https://learn.microsoft.com/en-us/rest/api/defenderforcloud/pricings).

### 보고서와 기존 결과

| 항목 | 계약 |
| --- | --- |
| 출력 | 실행별 `output/<실행시각-UTC>/`에 Excel·PPT·원본 JSON(raw·evidence·meta 통합). manifest는 생성 시점의 파일 해시 기록 |
| PPT | Excel의 `3_SE 판정` API 등급과 `4_프로세스 점수` 수동 응답·증적 상한으로 생성. 인터뷰 입력 후 `easm-agent deck`으로 갱신. [입력 절차](../README.md#중요---인터뷰-입력-후-ppt-재생성) |
| PPT 상세 표 | 인터뷰 질문·SY 수집 항목은 왼쪽 정렬. 항목 번호와 점수를 별도 열로 구분(인터뷰: 평가 점수, SY: 실측 점수) |
| 실행 시각 | 마이크로초 포함 UTC·충돌 접미사를 폴더와 새 파일명에 동일 적용. 실제 수집 시각은 `collection.collected_at` 유지 |
| 원본 14개 시트 | 통합 템플릿의 폰트·크기·수동 문항·문서·인용 입력 보존. API 결과와 제공 수동 입력의 출처를 구분 |
| 3_SE 판정 | A열 SY 코드, G 충족률, I/K API 등급, M 판정 근거. 숨김 U:Y는 원본 API 판정·사유·조치. 과거 5개 시트 결과 읽기도 유지 |
| 근거 이동 | L열 수집결과는 같은 SY 코드의 수집결과 근거 행으로 이동하는 통합 문서 내부 링크. 외부 URL·파일·사용자 입력을 링크 대상으로 쓰지 않음 |
| 원본·실패 | 15. 수집결과 근거, 16. 수집 Raw 데이터, 17. 수집이슈 Raw 데이터, 18. 필드누락사유. 원래 숫자·불리언·null·JSON 및 evidence_refs 보존 |
| 리소스 이름 | 수집결과 근거 요약은 최대 3개와 나머지 건수. 하단 두 번째 표에 전체 이름·분류·구독·리소스 그룹·ID 기록. 목록은 준수 증거가 아님 |
| 집계 | 인터뷰 54개·SY 26개, 총 80개. 프로세스 응답에 증적 상한을 적용하며 빈칸·N/A 제외. 4개 인터뷰 관점·SY 확보 시 영역, 6개 영역 확보 시 종합 산정 |
| 괴리 보정 | 인터뷰 평균 - SY 평균 >= 1.5이면 SY 평균 + 1.0으로 하향 보정, 소수 첫째 자리 반올림. 미확보를 0으로 보간하지 않음 |
| 템플릿 갱신 | `python -m scripts.merge_assessment --source <검토할-xlsx> --output <다른-경로.xlsx>`. 원본 덮어쓰기 금지. 패키지에도 템플릿 포함, 누락 시 오류 |
| 기존 결과 | `easm-agent package --output-dir output`은 최신 실행의 Excel·PPT 재생성. 특정 실행 폴더·기존 평면 구조 지원. 기본적으로 기존 파일명·판정 보존 |

### PPT 작성 지침

PPT는 항상 같은 형식으로 나오도록 아래 규칙을 따릅니다. 코드는 `report_pptx.py`(도형 갱신), `report_story.py`(수치 계산), `report_narrative.py`(문장), `report_terms.py`(각주 용어 사전)입니다.

| 구분 | 지침 |
| --- | --- |
| 템플릿 | 제공된 27장 [원본](assessment-report-template.pptx)의 배경·마스터·테마·미디어를 보존합니다. 텍스트·표·동적 막대만 갱신하며, 26개 항목 표·각주 간격에 필요한 행 높이·글자 크기만 조정합니다. 슬라이드·노트 XML 외 ZIP 부품은 기본 템플릿과 바이트 동일해야 합니다. 과거 12장 도형 계약도 회귀 테스트합니다. |
| Excel 연결 | `3_SE 판정`의 저장된 API 값과 `4_프로세스 점수`·`5_문서 실사`·`6_인터뷰 기록`의 수동 입력을 사용합니다. JSON 없는 Excel 단독 변환도 API 등급·충족률·분자·분모를 표시하되 데이터 구분·라이선스·플랫폼 범위를 추측하지 않습니다. |
| 비즈니스 페이지 | 사업 목표·VOC·생산성·출시 일정·성과는 원문 참고 자료로 보존하며 표지에서 API 검증 결과가 아님을 명시합니다. 개선 범위·기간은 제안이지 실행 완료가 아닙니다. |
| 표시 정밀도 | 비용 분자·분모가 통화 반올림으로 같아 보이는 경우에도 충족률을 함께 표시합니다. 0%·100% 근처 값이 반올림만으로 부재·완전 충족으로 보이지 않게 합니다. |
| 고정 문구 | 슬라이드 제목, 소제목, 표 머리글, 차트 라벨은 템플릿 원문을 유지합니다. 예: Executive Summary, CxO별 시사점, Lifecycle, Demand~Optimize, System Evidence, Phase 1~3, Iteration 1~3. |
| 수준 표기 | L1~L5, L2.9, 목표 L3 형식으로 씁니다. 한글 단계 표기(3단계 등)로 바꾸지 않습니다. |
| 숫자 | 모든 값은 raw JSON과 Excel 점수에서 계산하며 하드코딩하지 않습니다. 값이 채워지면 판정·막대·과제에 자동 반영합니다. |
| 문장 | 각 장 상단 회색 한 줄은 결론 한 문장으로 씁니다. 본문은 근거 수치와 비즈니스 영향을 비엔지니어 용어로 쓰고 항목 코드는 표의 코드 열에만 둡니다. 확인하지 못한 사실(유출 발생, 손실 금액 등)은 단정하지 않고 가능성으로 씁니다. |
| 값이 없을 때 | `N/A`, 사유 코드, 시트 번호를 쓰지 않고 '확인 중'으로 표시합니다. 0점이나 L1로 대체하지 않으며 평균에서 제외합니다. 판정 분포에는 '확인 중' 칸을 따로 둡니다. |
| 대체 지표 | 원천이 없는 보고서 전용 지표는 수집된 유사 지표로 대체하고 각주에 범위를 씁니다. 월별 신규 등록은 Agent 365 목록 패키지 기준이며 `created_at`이 테넌트 등록일이 아닐 수 있어 '월 신규 목록 패키지(Agent 365 목록)'로 표기하고 Agent 수·고유 Agent 수라고 쓰지 않습니다. 월 경계는 KST(Asia/Seoul)이며 청구 월은 청구일 기준입니다. 직접 만든 Agent는 `platform`으로 구분해 함께 보여 주고 Azure 에이전트와 다른 모집단임을 각주에 씁니다. 'Microsoft 제공 앱'이라고 쓰지 않습니다. |
| 라벨 | 라벨은 지표의 실제 의미를 따릅니다. 역할 할당이 확인된 환경 비율을 '제작 권한 통제'(DM-SY-01), 프로젝트 평가 실행 이력을 '배포 전 평가'(BI-SY-09), 청사진 연결 비율을 '책임 소재 기록'(DP-SY-15)이라고 쓰지 않습니다. 목표(80%)를 넘은 항목은 '체계 확보'가 아니라 '목표 충족, 나머지 보완 필요'로 씁니다. 같은 데이터는 한 판정 함수로 2장·3장에 같은 해석으로 씁니다. |
| 확인 중 사유 | 보안 권고(BI-SY-10)는 '보안 권고 N개 구독 확인, M개 구독 반영 대기(Defender 평가 반영 후 판정)'처럼 씁니다. Defender 플랜이 켜져 있는데 '활성화 후 판정'이라고 쓰지 않습니다. 월별 비용은 청구 행이 없는 달을 '청구 내역 없음'으로 쓰고 금액 달은 수집된 청구 일수와 리소스 단위 귀속을 각주에 씁니다. |
| 로드맵 | 과제 표에는 L3 미달·확인 중 항목만 올리고 L3 항목은 'L4 상향'(목표 90% 이상)으로 구분합니다. 현재값이 목표를 넘는 행은 두지 않으며 목표 수준 막대는 계획(안)이므로 '확보'로 단정하지 않습니다. |
| 단위 | 항목 수는 '개'·'곳'·'건', 금액은 `$0.40`처럼 통화로 씁니다. 100% 미만 비율은 `99.8%`처럼 소수 한 자리까지 씁니다. 금액이 작으면 '비율은 참고용'을 각주에 씁니다. |
| 각주 | 생소한 용어는 윗첨자 번호와 하단 각주(8pt 이상)로 풀어 씁니다. 용어 풀이는 `report_terms.py` 한 곳에서 관리하며 해당 장에 쓰인 용어만 넣습니다. |
| 표시 금지 | 가상·예시·실측 별도 같은 표식, 사유 코드, 내부 시트 번호를 쓰지 않습니다. |
| 생성 순서 | `collect`·`package`에 `--interview-workbook`으로 수동 입력 원본을 지정합니다. `package`에서 생략하면 기존 결과 Excel의 입력을 보존합니다. `deck`은 Excel 단독 재변환입니다. |
| 역방향 값 계약 | `report_values.py`가 PPT 표시값 → Excel 셀 → 제공 수동 입력·저장 API 값을 연결합니다. `report-values --workbook <결과.xlsx> --output <새.json>`으로 추출하며 원하는 점수에 맞춰 측정값을 조작하지 않습니다. |
| 실패 산출물 | 수집 시작의 인증·접근 실패는 원문 오류·비밀값 대신 표준 사유를 기록하고 N/A 26개 Excel·PPT를 생성, 종료 코드 2를 반환합니다. 설정 오류·템플릿 손상·출력 권한 오류는 명시적으로 실패합니다. |

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
| Graph 앱 읽기 | `AgentIdentity.Read.All`, `AgentIdentityBlueprint.Read.All`, `Application.Read.All` 및 테넌트 관리자 동의 |
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
| cleanup-apply | 승인 구독의 해당 SP 역할 할당을 먼저 회수하고 앱·SP 부재를 재조회한 뒤 정확히 일치하는 진단 사용자 지정 역할만 정리 |
| 역할 보존 | 다른 주체의 활성·PIM 적격 할당(현재 적격 인스턴스와 향후 적격 예약의 모든 페이지) 또는 재사용 계획이 있으면 보존. 조회 실패를 미사용으로 간주하지 않으며 plan의 `delete_after_target_assignments`는 해당 SP 할당 회수 후에만 삭제 가능하다는 뜻 |
| 삭제 확인 | 삭제 직전 사용 여부를 재조회하고 역할 DELETE 후 승인 구독 전체의 동일 역할 ID 부재를 최대 6회 확인. 전파 대기 중 DELETE를 반복하지 않으며 조회 실패·지속 존재는 성공 아님 |
| 종료 확인 | SP 삭제만으로 RBAC 제거를 가정하지 않고 홈 테넌트 앱·SP 잔여와 Graph 동의 철회를 확인. Step 5 Delete 캡처는 위치 안내이며 삭제 완료 증거 아님 |
| 로컬·별도 승인 | 인증서·개인키·암호 환경변수·경로 기록·setup.json·CLI 세션·공유 보고서·증적 사본은 승인 보관 정책에 따라 정리하고 임시 PIM 종료. 스크립트는 영구 삭제·파일 폐기·데모 삭제를 하지 않으며 삭제 앱은 30일 복원 가능할 수 있으므로 완전 폐기는 고객 승인 후 별도 수행 |

공식 근거: [PIM 적격 인스턴스 2020-10-01](https://learn.microsoft.com/en-us/rest/api/authorization/role-eligibility-schedule-instances/list-for-scope?view=rest-authorization-2020-10-01), [향후 적격 예약 2020-10-01](https://learn.microsoft.com/en-us/rest/api/authorization/role-eligibility-schedules/list-for-scope?view=rest-authorization-2020-10-01), [앱 삭제](https://learn.microsoft.com/en-us/entra/identity-platform/howto-remove-app), [복원·영구 삭제](https://learn.microsoft.com/en-us/entra/identity-platform/howto-restore-app), [SP 삭제 후 RBAC](https://learn.microsoft.com/en-us/azure/role-based-access-control/troubleshooting#symptom---role-assignments-with-identity-not-found), [사용자 지정 역할 삭제](https://learn.microsoft.com/en-us/azure/role-based-access-control/custom-roles#delete-a-custom-role).

## 공식 API와 읽기 계약

- 현재 Azure Public Cloud만 지원하며 소버린 클라우드 호스트·audience는 추측하지 않습니다. 실행 의존성은 `pyproject.toml`의 azure-identity·requests이며 아래 SDK 버전은 REST 확인 근거이지 설치 요구가 아닙니다.
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
| 보안 점수 참고 | GET `/subscriptions/{id}/providers/Microsoft.Security/secureScores`, `2020-01-01`. [안내](https://learn.microsoft.com/azure/defender-for-cloud/secure-score-security-controls#get-your-secure-score-from-the-rest-api) | `ascScore`, `score.current/max/percentage`(0~1) 실측. 현재 BI-SY-10 등급에는 미사용 |
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
- [공식 공급자 작업](https://learn.microsoft.com/azure/role-based-access-control/permissions/ai-machine-learning#microsoftcognitiveservices)의 agents/read·evaluations/read를 확인했고, 평가 목록 403에서 assets/read 요구를 확인해 v2 읽기 역할에 추가했습니다(v1은 변경하지 않음). 수집기는 평가 관련 목록만 호출합니다.
- agents/read에는 threads/messages 읽기도 포함됩니다. 더 세밀한 Agent 메타데이터 전용 DataAction을 추측하지 않으며 실제 서비스 인가·테넌트 상태는 사전 점검으로 확인합니다. 사용자 지정 역할의 AssignableScopes는 입력 구독이며 기본 할당은 승인 구독 상속입니다. [사용자 지정 역할 규칙](https://learn.microsoft.com/azure/role-based-access-control/custom-roles).
- 클래식은 명시적 `classic_v1`에서만 GET `/assistants?api-version=v1`을 사용합니다. [azure-ai-agents 1.1.0 연산](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agents_1.1.0/sdk/ai/azure-ai-agents/azure/ai/agents/operations/_operations.py), [설정](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agents_1.1.0/sdk/ai/azure-ai-agents/azure/ai/agents/_configuration.py).
- 초기 평가 `/evaluations/runs?api-version=2025-05-15-preview`는 이력이며 신규 프로필로 자동 대체·역전환하지 않습니다. [azure-ai-projects 1.0.0b11 연산](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_1.0.0b11/sdk/ai/azure-ai-projects/azure/ai/projects/operations/_operations.py), [설정](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_1.0.0b11/sdk/ai/azure-ai-projects/azure/ai/projects/_configuration.py).
- Red team은 공식 GET `/redTeams/runs?api-version=v1` 요청이 HTTP 401과 evaluations/write 요구로 거부되어 제외했습니다. 쓰기 권한 확대·일반 평가로 대체하지 않습니다.

### Entra Agent ID 계약

| 조회 | Graph v1.0 읽기 계약 |
| --- | --- |
| Blueprint | GET `/applications/microsoft.graph.agentIdentityBlueprint`, `AgentIdentityBlueprint.Read.All`. [공식 목록](https://learn.microsoft.com/graph/api/agentidentityblueprint-list) |
| Agent ID | GET `/servicePrincipals/microsoft.graph.agentIdentity`, `AgentIdentity.Read.All`. [공식 목록](https://learn.microsoft.com/graph/api/agentidentity-list) |
| 소유자·스폰서 | GET `/servicePrincipals/{id}/microsoft.graph.agentIdentity/owners` 또는 `/sponsors`, `$select=id,accountEnabled`. 사람 이름·UPN 없이 관계 수를 보관. accountEnabled는 기본 권한에서 제한될 수 있는 참고 속성이며 OE-SY-16 충족 조건에 미사용 |
| 앱 역할 | GET `/servicePrincipals/{id}/appRoleAssignments`, `Application.Read.All`. 대상 리소스 SP의 `appRoles`로 역할 이름 해석 |
| 제외 | 위임 동의는 Directory.Read.All로 범위를 넓혀야 하므로 수집 안 함. ARM 관리 ID를 Graph Agent Identity로 간주하지 않음 |

- 모든 Graph 진단 호출은 GET이며 `graph.microsoft.com`에만 토큰을 보냅니다. Agent ID·Blueprint는 태그의 구독·계정·프로젝트·Agent 식별자로 매칭합니다.

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
| 웹 로그인 보호 | App Service `config/authsettingsV2`, ARM `2024-11-01`. 인증 필수·동일 tenant issuer·allowedPrincipals.identities, `/health`만 예외. [스키마](https://learn.microsoft.com/azure/templates/microsoft.web/sites/config-authsettingsv2). 비밀번호 없는 로그인은 `OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID`·앱 전용 User Assigned MI·Graph federatedIdentityCredential 사용([MI 로그인](https://learn.microsoft.com/azure/app-service/configure-authentication-provider-aad#use-a-managed-identity-instead-of-a-secret), [신뢰](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-config-app-trust-managed-identity)) |
| 앱 등록 | Graph v1.0 applications·servicePrincipals·federatedIdentityCredentials. 단일 테넌트·승인 redirect URL·소유 표식이 있는 샘플 앱만 재사용. [앱](https://learn.microsoft.com/graph/api/application-post-applications?view=graph-rest-1.0), [연합 자격증명](https://learn.microsoft.com/graph/api/application-post-federatedidentitycredentials?view=graph-rest-1.0) |
| 샘플 평가·런타임 | OpenAI-compatible evals·runs, custom item_schema·string_check(eq)·jsonl/file_content로 실제 응답·정답 비교. 관리자만 terminal status·output_items 조회. 웹 앱 MI가 SDK responses.create·LangChain create_agent로 추론하고 진단 SP는 추론하지 않음. [정의](https://learn.microsoft.com/azure/foundry/reference/rest/evals-create-eval), [실행](https://learn.microsoft.com/azure/foundry/reference/rest/evals-create-eval-run), [데이터셋](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-datasets) |
| 인증서 | Graph application GET `$select=keyCredentials`로 기존 공개키를 보존하고 이번 임시 UUID만 추가·제거. 확보 불가 시 수정 안 함. 만료는 실제 not_valid_after_utc와 일치. [앱 갱신](https://learn.microsoft.com/graph/api/application-update?view=graph-rest-1.0), [keyCredential](https://learn.microsoft.com/graph/api/resources/keycredential?view=graph-rest-1.0) |
| 배포 확인 | 공식 Kudu ZIP의 이번 새 작업 ID·status=4·complete=true·실제 health 확인. 다른 origin·HTTP Location에 bearer 전송 금지. [Kudu API](https://github.com/projectkudu/kudu/wiki/Deploying-from-a-zip-file-or-url) |
| 증거 경계 | 관리자 `published_at`·관측 시각은 운영 배포 증거가 아니며 Reader 판정에 주입하지 않음. 모델 배포는 목록·쿼터만으로 가능성을 확정하지 않고 validate 통과 후 사용. 정확 일치 3문항 평가는 종합 보안·품질 검증이 아님 |

## 미확정 범위와 이기종 Agent

- 게시·운영 배포 API와 Agent-평가-배포 lineage는 추가 검증이 필요합니다. created_at을 배포 시각으로 바꾸지 않으며 프로젝트 완료 평가를 배포 전 평가로 해석하지 않습니다.
- 메트릭 dimension의 Agent 식별력·90일 미사용 증명 가능성은 확정하지 않았습니다. 현재 지표는 리소스 단위 수치 표본 관측 범위입니다.
- Power Platform 값은 공식 PowerShell 모듈 `Microsoft.PowerApps.Administration.PowerShell`(2.0.220 이상)의 읽기 명령, 환경 목록 API 또는 아래 문서화된 DLP V2 읽기 계약으로 별도 관리자가 내보냅니다. UI 내부의 미확인 API를 추측 호출하지 않습니다.
- 모든 권한이 있어도 제품 기능·라이선스·데이터가 없을 수 있습니다. 403은 IAM·방화벽·Private Endpoint 모두 가능하며 permission_denied로 남기되 원인을 단정하지 않습니다. license_missing은 명시적 라이선스 상태 응답에만 사용합니다.
- LangChain 앱 설정 list는 비밀을 반환할 수 있어 기본 수집에서 호출하지 않습니다. 승인 태그·메타데이터 또는 명시적 CSV 입력을 사용합니다.
- 공통 AgentEvidence는 platform과 필드별 null 사유로 플랫폼 차이를 보존합니다. 같은 이름의 Foundry Agent도 platform·subscription_id·resource_id·agent_id 복합 키로 구분하며 공유 리소스의 비용·사용량을 중복 귀속하지 않습니다.
- `easm-agent collect --manual-agents config/manual_agents.csv`는 manual/other 플랫폼의 직접 등록이며 Google/AWS 자동 수집이 아닙니다. 최소 필드는 agent_id·agent_name·platform이고 날짜는 시간대 포함 ISO 8601, tags·tools·usage_30d·field_status는 JSON입니다. 빈 값은 null + not_found이며 0으로 채우지 않습니다. 수동 Agent는 인벤토리·플랫폼 개수에만 포함하고 Azure 전용 SY 분모에 섞지 않으며 CSV 행 evidence_refs로 API 실측과 구분합니다.
- 확장 Collector Protocol은 `discover(subscriptions)`와 `required_roles`를 사용합니다. API Management AI Gateway·OpenTelemetry gen_ai 연계는 재사용 후보이며 구현·검증 완료로 표시하지 않습니다.

## 관리자 읽기 3개 항목의 계산 범위

계산식·한계는 [26개 API 지표](#26개-api-지표)를 따르며 진단 SP에 관리자 권한을 부여하지 않습니다. 별도 관리자 증적이 없으면 판정 보류입니다. 내보내기에는 환경별 역할 건수(`role_counts`)와 정책 적용 범위(`policies`)만 포함하며 사람·정책 내용은 저장하지 않습니다. `role_counts`에 대상 환경의 건수가 없으면 0건으로 추정하지 않고 확인된 0건만 명시적 `0`으로 기록합니다. 근거: [환경 목록 API 2024-10-01](https://learn.microsoft.com/en-us/rest/api/power-platform/environmentmanagement/environments/list-environments-for-user), [Agent 설정 화면](https://learn.microsoft.com/en-us/microsoft-agent-365/admin/agent-settings).

## 관리자 읽기 내보내기

진단 SP 대신 승인된 관리자가 별도로 실행하는 읽기 전용 도구입니다. 모듈 설치·역할 부여·정책 변경은 수행하지 않습니다. Power Platform 관리 SP 등록은 테넌트 관리자 수준 권한을 부여하므로 진단 SP에 적용하지 않습니다.

| 원천·계약 | 보관 값·한계 |
| --- | --- |
| 환경 GET, API 2024-10-01 | Azure CLI 관리자 사용자 로그인. 관리자 접근 가능 환경의 id·displayName·type·protectionLevel·azureRegion만 저장. 누락 필드는 `null`, `@odata.nextlink` 전체 페이지 확인 |
| Microsoft.PowerApps.Administration.PowerShell 2.0.220 이상 | Add-PowerAppsAccount 후 Get-AdminPowerAppEnvironmentRoleAssignment·Get-AdminDlpPolicy. 비 Dataverse 환경별 역할 할당 건수와 DLP 정책의 환경 적용 범위(`FilterType`·환경 ID)만 저장 |
| DLP V2 API | `GET https://api.bap.microsoft.com/providers/PowerPlatform.Governance/v1/policies?$top=50`. 공식 모듈 2.0.220의 Get-DlpPolicy 경로와 [관리자 커넥터 ListPoliciesV2](https://learn.microsoft.com/en-us/connectors/powerplatformforadmins/#list-dlp-policies-v2) 계약. v1 경로·nextLink 페이지 처리. 별도 관리자 위임 토큰 audience는 `https://service.powerapps.com/`. `environmentType`·`environments[].name`만 저장하며 알 수 없는 범위는 추정하지 않음 |
| DLP API 실패 | 승인된 현재 Azure CLI 사용자만 사용. 진단 SP·다른 테넌트 토큰 거부. 성공한 빈 목록은 정책 0건, 403·미완료 페이지·필수 필드 누락은 null과 사유. 자동 로그인·권한 변경·정책 쓰기·커넥터/사람 원문 저장 없음 |
| Copilot 기존 평가 API | [GET testruns 2024-10-01](https://learn.microsoft.com/en-us/rest/api/power-platform/copilotstudio/bots/list-maker-evaluation-test-runs), [자동화 문서](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-rest-api)는 Standard 하니스 범위를 명시. [PAC CLI 목록 명령](https://learn.microsoft.com/en-us/power-platform/developer/cli/reference/copilot-studio#pac-copilot-studio-list-maker-evaluation-test-runs)도 같은 API. 403은 권한 거부이지 미지원·실행 0건의 근거가 아님 |
| 평가 GET 위임 권한 | 403 `InsufficientDelegatedPermissions`의 필수 scope는 `CopilotStudio.MakerOperations.Read`. Power Platform API 서비스 정의상 활성 User 위임 권한이며 에이전트·채널 읽기만 허용. Microsoft 소유 Azure CLI 앱의 scope 추가가 `AADSTS65002`이면 별도 단일 테넌트 공용 읽기 앱과 현재 사용자 동의를 사용. 진단 SP·관리자 역할 변경 및 테넌트 전체 동의 없음 |
| 하니스별 관측 한계 | 문서상 Standard 기본 범위와 별개로 GitHub Copilot·Copilot Chat 하니스의 공식 동일 GET에서 읽기 앱 사용자 인증으로 200과 빈 value 목록을 확인. 다른 테넌트·모든 하니스의 지원을 보장하지 않으며, 별도 읽기 앱을 명시한 실제 응답만 평가. 미조회는 범위 밖 유지, 명시적 조회 실패는 null과 사유. API·화면이 일치하면 API를 우선하고 상충하면 보류 |
| 새 하니스 평가 | [새 Agent 경험의 평가 결과 문서](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/analytics-agent-evaluation-view)는 UI·CSV 내보내기를 안내하며 동일 REST 범위를 보장하지 않음. 공식 GET 응답을 검증하지 못한 하니스는 실제 승인 화면의 제한된 관측만 사용 |
| 승인된 Power Platform 관리 센터 화면 | `source_type=official_admin_portal_read`. 비 Dataverse 환경별 Environment Admin·Environment Maker 실제 할당 목록과 DLP 정책 목록을 읽기 전용으로 확인. PowerShell 결과로 표시하지 않음 |
| 실패·출처 | 모듈 부재는 feature_unavailable, 조회 실패는 건수 `null`. JSON의 테넌트·시간·명령·모듈 버전·범위를 확인하고 마스킹된 증적과 SHA256 보관. 해시는 원천 인증 서명이 아님 |

저장소를 준비한 별도 관리자 터미널에서 실행합니다. PowerShell 도구는 승인된 Windows PowerShell 5.1 실행 환경과 공식 모듈이 필요하며 토큰은 파일·증적에 저장하지 않습니다.

승인된 PowerShell 저장소 이름을 명시합니다. 다른 저장소로 자동 전환하거나 기존 저장소를 등록·덮어쓰지 않습니다.

```powershell
$repository = "<승인된-저장소명>"
Find-Module Microsoft.PowerApps.Administration.PowerShell -MinimumVersion 2.0.220 -Repository $repository -Verbose
Save-Module Microsoft.PowerApps.Administration.PowerShell -RequiredVersion 2.0.220 -Repository $repository -Path .easm-agent\tools\psmodules -Verbose
$env:PSModulePath = (Resolve-Path .easm-agent\tools\psmodules).Path + [IO.Path]::PathSeparator + $env:PSModulePath
Import-Module Microsoft.PowerApps.Administration.PowerShell -MinimumVersion 2.0.220 -Verbose
```

- 모듈이 승인된 저장소에 없으면 명시적으로 중단합니다. PowerShellGet·NuGet 공급자 호환, 의존성 해결, 다운로드, 실행 정책·가져오기 오류를 구분하며 `-Verbose`로 진단하고 근거 없이 TLS 문제로 단정하지 않습니다.
- 실행 정책으로 차단되면 IT가 승인한 실행 환경을 사용하거나 아래 관리 센터 화면 증적으로 진행합니다. `ExecutionPolicy Bypass`·정책 변경·인증서 검증 해제·보안 제어 변경은 수행하지 않습니다.

| 도구 | 데스크톱 | 창이 없는 터미널(Codespaces·SSH·원격) |
| --- | --- | --- |
| 환경 내보내기 | `az login --tenant <테넌트-ID>` | `az login --tenant <테넌트-ID> --use-device-code` |
| Power Platform (`-Service PowerPlatform`) | `-Login Interactive`(기본) 또는 `-Login Browser`(`-UseSystemBrowser`) | 공식 모듈에 장치 코드 로그인이 없어 `feature_unavailable`로 기록. 데스크톱에서 실행한 JSON을 사용 |

- `-Login Auto`(기본)는 `CODESPACES`·`SSH_CONNECTION`·`SSH_TTY` 설정, 비대화형 세션 또는 Linux의 디스플레이 부재를 창 없는 환경으로 보고 `DeviceCode`를 선택합니다. 그 외에는 `Interactive`입니다.

```powershell
python scripts\export_admin_environments.py --tenant-id <테넌트-ID> --output .easm-agent\admin-exports\environments.json
python scripts\export_dataverse_roles.py --tenant-id <테넌트-ID> --output .easm-agent\admin-exports\dataverse-roles.json
.\scripts\export_admin_evidence.ps1 -TenantId <테넌트-ID> -Service PowerPlatform -OutputPath .easm-agent\admin-exports\powerplatform.json -Login Browser
```

관리자 JSON만 전달하고 기존 결과에 반영합니다. 원래 Azure 수집 시각은 유지되며 각 관리자 조회 시각을 별도로 기록합니다. 원본 증적이 내장된 이식형 결과에는 해당 실행 폴더의 `evidence/<내보내기반영시각>/`에 새 증적을 보관합니다. 새 수집에서도 같은 `--admin-evidence-file`을 반복 지정할 수 있습니다.

```powershell
easm-agent package --output-dir output\<실행폴더> --tenant-id <테넌트-ID> `
  --admin-evidence-file .easm-agent\admin-exports\environments.json `
  --admin-evidence-file .easm-agent\admin-exports\powerplatform.json --reassess
```

- `--reassess`는 첨부한 증적을 등급에 반영합니다. `package`는 Excel을 새로 만들므로 인터뷰 입력본을 먼저 별도 보관합니다.
- 공식 근거: [역할 할당 조회](https://learn.microsoft.com/en-us/powershell/module/microsoft.powerapps.administration.powershell/get-adminpowerappenvironmentroleassignment), [DLP 정책 조회](https://learn.microsoft.com/en-us/powershell/module/microsoft.powerapps.administration.powershell/get-admindlppolicy), [관리 SP 권한 한계](https://learn.microsoft.com/en-us/power-platform/admin/powershell-create-service-principal).

### Gallery 접근 제한 시 대안

| 경로 | 확인한 기능 | 평가 적용 한계 |
| --- | --- | --- |
| [공식 PAC CLI](https://learn.microsoft.com/en-us/power-platform/developer/cli/reference/admin#pac-admin-dlp-policy-list) | `pac admin dlp-policy list`, `show --policy-name <정책-ID>`. Gallery 대신 [NuGet](https://learn.microsoft.com/en-us/power-platform/developer/howto/install-cli-net-tool) 또는 [MSI](https://learn.microsoft.com/en-us/power-platform/developer/howto/install-cli-msi)로 설치 | DLP 조회만 지원. 정책 적용 범위·환경 ID·전체 조회 완료를 확인해야 하며 Dataverse `list-roles`는 역할 정의 목록이므로 DM-SY-01의 역할 할당으로 쓰지 않음 |
| Power Platform 관리 센터 | 비 Dataverse 환경의 [환경 관리자·환경 제작자 역할](https://learn.microsoft.com/en-us/power-platform/admin/database-security)과 [DLP 정책 적용 범위](https://learn.microsoft.com/en-us/power-platform/admin/prevent-data-loss) 확인 | 승인된 관리자 로그인 필요. 역할 정의가 아닌 실제 할당과 모든 정책의 포함·제외 환경을 확인. 변경은 수행하지 않음 |
| [환경 역할 할당 REST API](https://learn.microsoft.com/en-us/rest/api/power-platform/authorization/role-based-access-control/list-environment-role-assignments) 2024-10-01 | 공식 Authorization API의 미리 보기 조회 | [Power Platform API 계층 RBAC](https://learn.microsoft.com/en-us/power-platform/admin/security/role-based-access-control)이며 기존 환경 관리자·제작자 할당과 동등함을 확인하지 못해 DM-SY-01 대체 증적으로 쓰지 않음 |

- 관리 센터 JSON은 `--admin-evidence-file`로 반영합니다. `command`는 역할 조회의 `/manage/environments` 또는 정책 조회의 `/security/dataprotection/dlp` 공식 URL이며 `module_version`은 `Power Platform admin center (browser)`로 기록합니다. 각 `portal_pages`에는 공식 화면의 정규 URL(쿼리 제외)·`observed_at`·`http_status=200`·`state=empty|populated`·확인된 `object_count`를 기록합니다.
- 필터 없는 전체 목록을 확인한 승인된 관리자만 내보냅니다. 역할은 환경별 두 화면의 합계, 정책은 목록 건수와 범위가 일치해야 합니다. 조회 실패·로딩 중 화면을 빈 목록으로 기록하지 않으며 확인하지 않은 환경 역할은 `null`을 유지합니다. 파일 해시는 원천 인증 서명이 아니며 개인 이름·사용자 이름·토큰은 저장하지 않습니다.
- 조직 전체 대상 역할 할당은 고유 사용자 수나 최소 권한의 적정성을 뜻하지 않습니다. PAC CLI 출력은 아직 수용하지 않으며 승인된 화면 증적과 공식 PowerShell 증적은 구분해 보관합니다.
- 실제 조직의 저장소 주소·계정·테넌트·구독 식별자와 수집 결과는 공개 문서에 기록하지 않습니다. 로컬 설정·모듈·증적·보고서는 Git 제외 경로에서만 보관하며 공개 배포 파일에 포함하지 않습니다.

