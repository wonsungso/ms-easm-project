# 개발용 데모

**개발·검증 전용입니다.** 고객 절차는 [README](../README.md)를 따릅니다. 관리자 배포와 진단 SP의 읽기 수집은 분리합니다.

| 데모 | 위치 |
| --- | --- |
| Azure·M365 | 이 문서. Foundry·Copilot Studio·Agent Builder |
| AWS·Snowflake | [이기종 데모 배포](./connected-platforms.md). 고객 워크로드 연결은 [이기종 에이전트 설정](../docs/connected-platforms.md) |

## 배포와 실행

| 준비·범위 | 내용 |
| --- | --- |
| 실행 위치·권한 | 프로젝트 루트, 승인된 관리자, `.easm-agent/setup.json` |
| 입력 | `tenant_id`·`subscription_ids`·`account_name`, [config.yaml](config.yaml)의 SaaS 테넌트·환경·게시자·라이선스 확인 |
| 배포 대상 | Foundry·모델·로그, 개인 범위 M365 선언형 Agent·Studio 초안. [catalog.json](catalog.json): Foundry 11개 |
| 승인 조건 | Korea Central·소형 모델·합성 데이터, GlobalStandard 처리·공급자 등록 승인 |
| 진단 SP | 별도 준비. 없으면 진단 역할 생성·할당 생략 |

```bash
bash scripts/setup.sh login
bash demo/run.sh --apply
```

Foundry Agent 11개·합성 평가 5건을 준비합니다. 배포 전 테스트·Ruff·Bicep·ARM validate/what-if를 확인하며 삭제 계획은 차단합니다. 증거는 `.easm-agent/demo/validation.json`에 저장합니다. **USD 100은 예산이며 과금 상한이 아닙니다.**

## 개별 명령과 재개

| 목적 | 프로젝트 루트에서 실행 |
| --- | --- |
| 계획·테스트 | `python -m demo.manage plan` / `python -m demo.manage test` |
| 사전 검증 | `python -m demo.manage validate --prepare-providers` |
| 인프라 재사용 배포 | `python -m demo.manage deploy --apply --reuse-infrastructure` |
| Foundry Agent 준비·평가 | `python -m demo.agents --apply` |
| 기존 환경에 API 샘플 추가·수집 | `bash demo/run-samples.sh` |
| SaaS 코드 배포·검증 | `python -m demo.manage saas --apply` (실패한 Studio 초안은 `--reconcile`로 읽기 전용 재검증) |
| Reader 수집 | `python -m demo.manage collect` |
| Defender 플랜 적용·복원 | `python -m demo.manage defender --apply` / `--apply --revert`. 유료 설정·이전 상태를 기록 |
| Studio 초안 게시(관리자) | `python -m demo.manage studio-publish --apply`. 게시 후에야 인벤토리에 나타나며 반영에 시간이 걸림 |
| 기존 결과 검증 | `python -m demo.diagnostics verify` |
| Codespaces 검증 | `python -m demo.diagnostics codespace --codespace '<Codespace 이름>' --apply` |

| 운영 | 규칙 |
| --- | --- |
| 재개 | 실패한 단계만 재실행. 소유 태그·영수증 없는 리소스는 생성·변경하지 않음 |
| 인증 | 수집용 임시 인증서·저장소 밖 개인키만 준비하고 종료 후 정리 |
| 추가 읽기 권한 | 실제 403에만 제한적으로 적용. `auto_grant_needed_read_roles: false`로 비활성화 |
| Agent 365 | 관리자 `setup.sh --agent365-reader` 준비 후 `agent365_registry: true` 설정 |
| 상태 분리 | `EASM_AGENT_STATE_DIR`·`EASM_AGENT_LAB_CONFIG`에 별도 절대 경로 지정 |
| 결과 | [실행별 출력](../README.md#step-5). `verify`는 읽기만 수행 |

### API 샘플 추가와 반복 배포

**기존 환경에 샘플 추가·재수집:** `bash demo/run-samples.sh`. 같은 이름·환경·영수증을 재사용하여 중복 생성을 방지합니다.

| 플랫폼 | 샘플 조건 |
| --- | --- |
| Foundry | 최소 설명·평가 없음 / 설명·완료된 합성 평가 / 기존 추가 모델·MCP 승인 모드 |
| Copilot Studio | 최소 설명 / 구조화된 지침 / Classic 작성 형태. 공식 `msagent`로 생성·게시 |
| Agent Builder | 기존 UI 작성 Agent를 유지·수집. 공개 신규 생성 API가 확인되지 않아 Toolkit으로 대체하지 않음 |

- 설정은 `.easm-agent/demo/samples-config.json`이며 다른 환경은 `--config <파일>`로 지정합니다.
- 기존 Azure CLI·msagent 인증이 필요합니다. 새 환경·라이선스·관리자 역할은 만들지 않습니다.
- 환경·DLP·평가 이력은 **별도 관리자 API로 자동 내보내기**합니다. 새 Studio ID가 인벤토리에 반영된 뒤 진단 SP로 수집하며 실패·빈 분모는 `null`을 유지합니다.

## M365 선언형 Agent·Copilot Studio 코드 데모

`demo/run.sh --apply`는 사전 점검 후 Azure·Agent·SaaS를 배포합니다. [config.yaml](config.yaml)의 SaaS 입력은 기본 비어 있으며 승인된 값이 있어야 진행합니다.

| 구분 | 자동화·경계 |
| --- | --- |
| M365 | [공식 Toolkit scaffold](m365/easm-demo-declarative)·선언형 manifest·합성 지침. 개인 범위 `atk provision`만 실행하며 조직 카탈로그에 게시하지 않음 |
| 작성 출처 | Toolkit 코드 작성은 Agent Builder UI 작성과 다름. API의 `createdIn`을 유지하며 Agent Builder로 위장하지 않음 |
| Studio | 공식 Preview `msagent`의 로컬 정의·초안 push와 Dataverse ID·콘텐츠·미게시 상태 검증. 로컬 등록을 클라우드 생성 성공으로 취급하지 않음 |
| 준비 | 같은 테넌트 인증, 준비된 Dataverse 환경, 게시자·HTTPS URL·Studio 접두사, `licenses_confirmed` |
| 범위 | E7만으로 환경·용량을 추론하지 않음. 신규 환경·구매·자동 로그인 제외 |
| 수집 | `--collect`는 관리자 최소 필드 내보내기 후 진단 SP에 전달. 실패는 `null`·사유 유지 |
| 실행 OS | SaaS CLI 검증 경로는 Windows/macOS. Linux Codespaces는 가정하지 않음 |

```powershell
# 승인된 로컬 도구 설치 - 프로젝트 전용, 인증·클라우드 배포 없음
npm install --prefix .easm-agent\tools\m365-automation\atk @microsoft/m365agentstoolkit-cli@1.1.19
dotnet tool install Microsoft.Agents.Hosting.Cli --version 0.2.128-beta --tool-path .easm-agent\tools\m365-automation\msagent
```

Node 20.19/22.12 이상·.NET 10이 필요합니다. 비 Windows는 `msagent_executable`을 지정합니다. 환경 ID·계정·영수증은 커밋하지 않습니다. 과거 이력·업무 승인·인사 대사는 [별도 증적](../docs/api-notes.md#추가-보고서-증적)이 필요합니다.

### 실제 Agent Builder UI 작성·인벤토리 검증

Agent Builder는 공식 UI에서 작성하며 Toolkit 작성본으로 대체하지 않습니다.

| 순서 | 준비·검증 |
| --- | --- |
| 1 | `python -m demo.m365 plan` 후 승인된 테넌트·라이선스 확인 |
| 2 | Builder의 `EASM Demo Builder`와 Studio Agent 준비. 합성 지침·Entra 인증·제한된 공유 사용 |
| 3 | 게시·인벤토리 반영 후 승인된 읽기 사용자로 내보내고 실제 ID로 검증 |

```powershell
az login --tenant "<테스트 테넌트 ID>"
python scripts\export_copilot_inventory.py --tenant-id "<테스트 테넌트 ID>" --output copilot-inventory.json --approved
python -m demo.m365 verify --inventory-file copilot-inventory.json --tenant-id "<테스트 테넌트 ID>" --agent-builder-id "<실제 Agent ID>" --copilot-studio-id "<실제 Agent ID>"
```

`--require-published`는 실제 게시 시각을 요구합니다. ID가 모호하면 환경 ID도 지정합니다. 종료 0은 ID·작성 출처·게시 확인, 2는 미확인입니다. `collect --copilot-only`로 가져오며 정리는 승인된 소유자가 수행합니다.

### 라이선스 판단

구매·할당은 수행하지 않으며 실제 테넌트 계약·서비스 플랜을 확인합니다(2026-11-18 공식 문서 기준).

| 목적 | 필요 조건 |
| --- | --- |
| Agent Builder 기본 작성 | 적격 M365/Copilot Chat와 테넌트 정책. 조직 데이터 기능은 기능별 자격 확인 |
| Copilot Studio 작성·게시 | Microsoft 365 Copilot 또는 Studio 사용자·테넌트 용량·종량제. 평가판은 테스트만 가능하고 게시 불가 |
| Power Platform 인벤토리 | 위임 사용자·읽기 역할·API 사용 동의. E7을 필수로 처리하지 않음 |
| Agent 365 Graph 등록부 API·관측·도구 통제 | Agent 365 또는 E7(E5 + Copilot + Entra Suite + Agent 365). Power Platform 인벤토리와 별도 서비스 |

공식 근거: [개발 자격](https://learn.microsoft.com/en-us/plugins/prerequisites) · [Studio 라이선스](https://learn.microsoft.com/en-us/microsoft-copilot-studio/billing-licensing) · [E3·E5·E7](https://learn.microsoft.com/en-us/copilot/plan/compare-copilot-e3-e5-e7). 소스 변경만으로 인증·구매·게시가 완료되지는 않습니다.

```powershell
easm-agent collect --fixture tests\fixtures\copilot_agents.json --output-dir output --customer "<데모 고객사>"
```

## 데모 구성과 안전 경계

| 데모 항목 | 위치 | 결과가 갈리는 지점 |
| --- | --- | --- |
| 사용자 지정 콘텐츠 필터(RAI), 기반 `Microsoft.DefaultV2`, Hate 재정의 | [foundry.bicep](foundry.bicep) | 주 모델 배포만 사용자 지정 정책, 추가 배포는 기본 정책 |
| Action Group + 메트릭 경고 | [monitor.bicep](monitor.bicep) | Foundry `AzureOpenAIAvailabilityRate` 99 미만 |
| Azure Policy 내장 감사 할당 | [policy.bicep](policy.bicep) | Foundry 계정이 `publicNetworkAccess: Enabled`라 비준수 |
| Foundry Agent 함수 도구(`privacy-helper`)·원격 MCP 도구(`onboarding-helper`) | [catalog.json](catalog.json) | 함수는 스키마만 등록, MCP는 `learn.microsoft.com/api/mcp`·승인 `always` |

경고 수신자는 `Monitoring Reader`이며 정책은 `DoNotEnforce`·`Audit`입니다. 메트릭 경고 비용이 발생합니다. 도구 Agent는 정의만 확인하며 도구를 실행하지 않습니다.

| 경계 | 적용·한계 |
| --- | --- |
| 실행 신원 | Foundry 준비·합성 호출은 승인된 관리자이며 진단 SP의 수집과 별개 |
| 호출 | Foundry Agent endpoint의 합성 응답만 확인. 도구 Agent는 정의·승인 구성을 확인하며 도구를 실행하지 않음 |
| 평가 | 합성 응답 3문항 정확 일치 검사이며 종합 안전성·업무 품질 인증이 아님 |
| 관측 | 생성 직후에는 30일 비용·90일 관측을 확보할 수 없음. 미지원·권한 부족·유입 지연을 0·L1로 대체하지 않음 |

## 개발 검사와 정리

```bash
python -m pip install -e ".[dev,demo]"
python -m pytest -q
python -m ruff check src scripts demo tests
python -m demo.manage cleanup
```

`cleanup`은 기본 dry-run입니다. 실제 삭제에는 별도 승인과 `--apply --confirm-lab-id '<lab_id>'`가 필요합니다. 테넌트·소유 태그를 확인하며 기존 앱/SP·다른 리소스는 유지합니다.
