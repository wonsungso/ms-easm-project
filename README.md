# EASM 거버넌스 진단·수집

EASM(Enterprise Agent Service Management)은 **Agent의 구성·기록을 읽기 전용 API로 수집**하여 Excel·PPT·JSON을 만듭니다. 권한 설정·배포·정리는 승인된 관리자만 수행하며 진단 앱은 쓰기·삭제·비밀 조회를 하지 않습니다.

## 지원 Agent 플랫폼

| 플랫폼 | 수집 경로 | 평가 범위·조건 |
| --- | --- | --- |
| Microsoft Foundry | Azure·Foundry 읽기 API | Agent·모델·도구·평가·운영 구성 |
| Copilot Studio | Power Platform 인벤토리·기존 평가 읽기 API | 모델·접근·커넥터·게시·소유자 등 제공 필드 |
| Microsoft 365 Copilot Agent Builder | Power Platform 인벤토리 읽기 API | 구성·게시·소유자·평가 기록. Entra Agent ID 평가는 제외 |
| Amazon Bedrock Agents Classic·AgentCore | Agent 365 연결·동기화 후 Graph 패키지 API | 모델·접근·버전·소유자·원본 연결·리전 기록 |
| Snowflake Cortex Agents | Agent 365 연결·동기화 후 Graph 패키지 API | 접근·HTTPS endpoint·버전·소유자·원본 연결 기록. 활동 관측은 문서상 미지원 |

API 필드 미제공·조회 실패는 사유와 `null`로 보존합니다. **지원 플랫폼이라고 26개 항목 모두 충족하는 것은 아닙니다.**

| 문서 | 내용 |
| --- | --- |
| 아래 Step 1~6 | 준비·연결·수집·결과 확인·정리 |
| [점검 항목 상세](docs/checklist.md) | 항목별 계산 방식·한계·확인 화면 |
| [API 참고](docs/api-notes.md) | API·권한·평가·PPT 작성 계약 |
| [이기종 에이전트 설정](docs/connected-platforms.md) | 기존 AWS·Snowflake 워크로드 연결·화면별 설정 |
| [개발용 데모](demo/README.md) | 개발·검증 전용 테스트 환경. 고객 진단에는 불필요 |

## 진행 순서

| 순서 | 담당 | 실행 위치 | 할 일 |
| --- | --- | --- | --- |
| 1(이기종 선택) | <span style="background-color: #dcffe4; color: #24292f;">[고객사 담당자]</span> | <span style="background-color: #d6f5f2; color: #24292f;">[M365 Admin Center]</span> | 연결 전용 읽기 자격 증명 준비, Agent 365 연결·동기화 |
| 2 | <span style="background-color: #fff5b1; color: #24292f;">[MS EASM 관리자]</span> | <span style="background-color: #ddf4ff; color: #24292f;">[Codespaces]</span> 터미널 | 인증서 생성, 고객용 ZIP·공개 인증서 전달 |
| 3 | <span style="background-color: #dcffe4; color: #24292f;">[고객사 담당자]</span> | <span style="background-color: #ffe8d6; color: #24292f;">[고객 VM]</span> 브라우저 - Azure Portal | 진단 앱 등록, 공개 인증서 업로드 |
| 4 | <span style="background-color: #dcffe4; color: #24292f;">[고객사 담당자]</span> | <span style="background-color: #ffe8d6; color: #24292f;">[고객 VM]</span> Bash 터미널 | 읽기 권한 설정, `setup.json` 반환 |
| 5 | <span style="background-color: #fff5b1; color: #24292f;">[MS EASM 관리자]</span> | <span style="background-color: #ddf4ff; color: #24292f;">[Codespaces]</span> 터미널·로컬 Excel | 검증·수집, 인터뷰 점수 입력 후 PPT 확정 |
| 6 | <span style="background-color: #e5dcf7; color: #24292f;">[고객/MS 공동]</span> | <span style="background-color: #ddf4ff; color: #24292f;">[Codespaces]</span> / <span style="background-color: #ffe8d6; color: #24292f;">[고객 VM]</span> | 결과 검토, 권한 회수·키·데이터 정리 |

<a id="step-1"></a>

## Step 1. <span style="background-color: #dcffe4; color: #24292f;">[고객사 담당자]</span> <span style="background-color: #d6f5f2; color: #24292f;">[M365 Admin Center]</span> - Agent 365 Connected platforms

**AWS·Snowflake 수집에만 필요합니다.** [이기종 에이전트 설정](docs/connected-platforms.md)에 따라 연결 전용 읽기 자격 증명을 준비합니다.

[Microsoft 365 관리 센터](https://admin.cloud.microsoft/#/agents/all/connected-platforms?type=Platform)의 **Agents → All Agents → Connected platforms**에서 **Validate → Save → Sync agents**를 실행합니다. 기존 연결은 재사용하며 활동 수집은 별도 승인 없이는 켜지 않습니다.

`Success`·`Healthy`와 대상 목록을 확인한 뒤 Step 5의 `--agent365-registry`로 읽습니다. 포털 동기화 성공과 API 조회 성공은 별개입니다.

## Step 2. <span style="background-color: #fff5b1; color: #24292f;">[MS EASM 관리자]</span> <span style="background-color: #ddf4ff; color: #24292f;">[Codespaces]</span> - 환경·인증서 준비

- **환경 준비:** 저장소 **Code → Codespaces → Create codespace**에서 엽니다.
- **인증서 생성:** 아래 명령을 실행하고 개인키 암호는 안전하게 보관합니다.

```bash
umask 077
cert_dir="$HOME/.config/easm-agent/auth-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$HOME/.config/easm-agent"
mkdir -m 700 "$cert_dir" || exit 1
openssl req -x509 -newkey rsa:3072 -sha256 -days 90 \
  -subj '/CN=easmagent-diagnostic' \
  -keyout "$cert_dir/private-key.pem" -out "$cert_dir/public-cert.pem"
cat "$cert_dir/private-key.pem" "$cert_dir/public-cert.pem" > "$cert_dir/diagnostic.pem"
chmod 600 "$cert_dir/private-key.pem" "$cert_dir/diagnostic.pem"
mkdir -p .easm-agent
printf '%s\n' "$cert_dir/diagnostic.pem" > .easm-agent/certificate-path
```

- **고객 전달:** 프로젝트에 포함된 [**customer-setup.zip**](docs/downloads/customer-setup.zip) 파일과 위에서 만든 **public-cert.pem**을 전달합니다.

## Step 3. <span style="background-color: #dcffe4; color: #24292f;">[고객사 담당자]</span> <span style="background-color: #ffe8d6; color: #24292f;">[고객 VM]</span> - 진단 앱 등록

실행 위치: 고객 VM의 브라우저 - Azure Portal.

- **앱 등록:** [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID → 앱 등록 → 새 등록**에서 이름은 `easmagent-diagnostic`, 계정 유형은 **Single tenant**로 등록합니다.

![앱 등록 위치](docs/imgs/07-register-sp.png)

- **ID 확인:** **개요**에서 Tenant ID와 Client ID를 기록합니다. SP 개체 ID는 Step 4 스크립트가 자동 조회합니다.

![앱 ID 확인 위치](docs/imgs/08-sp-overview.png)

- **인증서 등록:** **인증서 및 암호 → 인증서 → 인증서 업로드**에서 받은 `public-cert.pem`을 등록합니다.

![공개 인증서 업로드](docs/imgs/09-upload-certificate.png)

- **MS에 전달:** Tenant ID, Client ID, 승인 구독 ID 목록.

## Step 4. <span style="background-color: #dcffe4; color: #24292f;">[고객사 담당자]</span> <span style="background-color: #ffe8d6; color: #24292f;">[고객 VM]</span> - 읽기 권한 설정

실행 위치: 고객 VM의 Bash 터미널.

- **부여 대상:** 아래 읽기 권한을 **모두 부여**합니다. Azure 역할과 Entra 권한은 별개입니다.

| 종류 | 권한 전체 이름 | 부여 범위 |
| --- | --- | --- |
| Azure | `Reader` | 승인 구독 |
| Azure | `Cost Management Reader` | 승인 구독 |
| Azure | `Log Analytics Reader` | 승인 구독 |
| Azure | `Security Reader` | 승인 구독 |
| Foundry 사용자 지정 역할 | `EASMAgent Foundry Evidence Reader v2` | 승인 구독의 프로젝트에 상속 |
| Graph 애플리케이션 권한 | `AgentIdentity.Read.All` | 테넌트, 관리자 동의 필요 |
| Graph 애플리케이션 권한 | `AgentIdentityBlueprint.Read.All` | 테넌트, 관리자 동의 필요 |
| Graph 애플리케이션 권한 | `Application.Read.All` | 테넌트, 관리자 동의 필요 |

Python 3.11 이상·Azure CLI·Bash와 구독 역할 설정·Entra 동의 권한이 필요합니다. **진단 앱에는 Owner·Contributor를 부여하지 않습니다.**

받은 [**customer-setup.zip**](docs/downloads/customer-setup.zip)을 압축 해제합니다.

```bash
python3 -m zipfile -e customer-setup.zip customer-setup
cd customer-setup
```

- **설정값 입력:** 아래 ID를 고객 환경의 값으로 바꾸어 `setup.json`을 생성합니다.

```bash
cat > setup.json <<'EOF'
{
  "tenant_id": "<고객 테넌트 ID>",
  "subscription_ids": [
    "<승인 구독 1 ID>",
    "<승인 구독 2 ID>",
    "<승인 구독 3 ID>"
  ],
  "account_type": "service-principal",
  "account_name": "easmagent-diagnostic",
  "client_id": "<진단 앱의 애플리케이션(클라이언트) ID>"
}
EOF
```

- **권한 설정 실행:** 로그인 후 부여할 권한을 확인하고 적용합니다.

```bash
bash setup.sh login
bash setup.sh plan     # 부여할 권한 확인, Azure 변경 없음
bash setup.sh apply    # 기본 읽기 권한 전체 부여 및 결과를 setup.json에 저장
```

- **완료 확인:** 요청한 권한이 `확인됨`이고 `setup.json` 저장 메시지가 있어야 합니다. 아래는 승인 구독 3개의 예시입니다.

![고객 VM 권한 설정 성공 결과 예시](docs/imgs/20-customer-setup-success.png)

- **Graph 동의 단계에서 중단될 때:** PIM에서 **Privileged Role Administrator 또는 Global Administrator**를 활성화한 관리자가 아래를 재실행합니다. Global Reader만으로는 동의할 수 없으며 기존 Azure 역할은 중복 생성하지 않습니다.

```bash
bash setup.sh login --login-resource graph
bash setup.sh apply
```

완료된 **`setup.json`만 MS에 반환**합니다. 관리자 인증 정보는 전달하지 않고 개인키는 MS가 보관합니다. Azure·Entra 관리자가 다르면 같은 파일로 이어서 진행합니다.

아래 화면은 확인용이며 **스크립트 성공 후 같은 권한을 포털에서 다시 부여하지 않습니다.**

<details>
<summary>권한 확인 화면 펼치기 - Azure 역할·Foundry·Graph</summary>

**구독 → 액세스 제어(IAM)**에서 진단 앱의 역할을 확인하고 누락 시에만 관리자가 추가합니다.

![Azure Reader 역할 선택 위치](docs/imgs/10-reader-role.png)

**Foundry:** 스크립트가 생성한 **EASMAgent Foundry Evidence Reader v2**를 확인합니다.

![Foundry 사용자 지정 읽기 역할 선택](docs/imgs/17-foundry-reader.png)

**Graph:** **Entra → 앱 등록 → 진단 앱 → API 사용 권한**에서 `AgentIdentity.Read.All`, `AgentIdentityBlueprint.Read.All`, `Application.Read.All` 3개 권한과 관리자 동의를 확인합니다.

![Graph 읽기 권한 3개와 관리자 동의 위치](docs/imgs/12-entra-consent.png)

나머지 Azure 역할도 같은 IAM 화면에서 확인합니다.

![진단 앱과 구독 범위 확인](docs/imgs/11-reader-review.png)

![Cost Management Reader 선택](docs/imgs/14-cost-reader.png)

![Log Analytics Reader 선택](docs/imgs/15-log-reader.png)

![Security Reader 선택](docs/imgs/16-security-reader.png)

- **Foundry 권한 확인:** **View → JSON** 또는 **Permissions → DataActions**에서 아래 읽기 권한 3개만 있는지 확인합니다.

| Foundry DataActions 전체 이름 |
| --- |
| `Microsoft.CognitiveServices/accounts/AIServices/agents/read` |
| `Microsoft.CognitiveServices/accounts/AIServices/evaluations/read` |
| `Microsoft.CognitiveServices/accounts/AIServices/assets/read` |

![Foundry JSON에서 읽기 DataActions 전체 이름 3개 확인](docs/imgs/18-foundry-permissions.png)

![관리자 동의 확인](docs/imgs/19-entra-confirm.png)

![Graph 읽기 권한 3개 승인 완료 확인](docs/imgs/13-entra-granted.png)

권한 누락 항목은 **판정 보류**이며 보완 후 다시 수집합니다.
</details>

<a id="step-5"></a>

## Step 5. <span style="background-color: #fff5b1; color: #24292f;">[MS EASM 관리자]</span> <span style="background-color: #ddf4ff; color: #24292f;">[Codespaces]</span> - 수집·보고서 확정

| 수집 대상 | 인증·범위 |
| --- | --- |
| Microsoft Foundry·Entra Agent ID | Step 4의 진단 앱 읽기 권한. 기본 범위는 접근 가능한 활성 구독이며 `setup.json`에 구독을 지정하면 해당 범위 사용 |
| Microsoft 365 Copilot Agent Builder·Copilot Studio | 별도 `Global Reader` 또는 `AI Reader` 사용자의 위임 읽기 내보내기 필요. V1 봇 제외 |
| Agent 365 패키지(AWS·Snowflake 포함) | `CopilotPackages.Read.All` 애플리케이션 권한·관리자 동의 및 Agent 365 라이선스(E7 포함 가능) |
| Power Platform 관리 구성(환경·역할·DLP) | 승인된 별도 관리자 읽기 증적. 진단 앱에 관리자 역할을 부여하지 않음 |

### 관리자 위임 읽기 내보내기

승인 관리자 터미널에서 API를 읽어 JSON을 수집 환경으로 전달합니다. 도구는 프로젝트에 포함되며 고객 ZIP에는 없습니다. **API 조회 파일은 A, 실제 화면 증적은 E**입니다. 토큰·사람 정보·대화는 저장하지 않습니다.

```powershell
az login --tenant "<테넌트 ID>"
```

| 내보내기 | 명령 | 반영 항목 |
| --- | --- | --- |
| Copilot 인벤토리·기존 평가 | `python scripts\export_copilot_inventory.py --tenant-id "<테넌트 ID>" --output copilot-inventory.json --approved --include-evaluations --evaluation-client-id "<읽기 앱 Client ID>"` | DS-SY-04~06, BI-SY-09·10·12·13, DP-SY-15, OE-SY-19·22 |
| 관리 환경 | `python scripts\export_admin_environments.py --tenant-id "<테넌트 ID>" --output environments.json` | DLP 분모·Copilot 지역 |
| DLP 정책 | `python scripts\export_dlp_policies.py --tenant-id "<테넌트 ID>" --output dlp-policies.json --approved` | DS-SY-02 |

- **평가 이력:** 새 평가를 실행하지 않습니다. 기본은 Standard 하니스이며 별도 읽기 앱은 `--evaluation-client-id`로 지정합니다. 성공한 빈 목록은 0건, 실패는 `null`입니다. 권한·공식 CLI 읽기는 [API 참고](docs/api-notes.md#copilot-인벤토리)를 따릅니다.
- **실제 화면 증적:** 승인된 검토 화면은 `--copilot-review-file <검토증적.json>`으로 첨부합니다. 같은 Agent의 API 결과와 상충하면 판정을 보류합니다.
- **수집 후 첨부:** `package --admin-evidence-file <파일> --tenant-id "<테넌트 ID>" --reassess`로 재평가합니다.
- **Agent 365:** 기본 권한에 없으므로 승인된 관리자가 `customer-setup` 폴더에서 `bash setup.sh plan --agent365-reader` 확인 후 `bash setup.sh apply --agent365-reader`를 실행합니다. AWS·Snowflake는 [Step 1](#step-1) 완료 후 수집합니다.

### 진단 앱 수집

- **준비:** 고객이 반환한 `setup.json`을 저장소의 **.easm-agent/setup.json**으로 저장합니다.
- **실행:** **Step 2에서 사용한 동일 Codespaces 터미널의 저장소 루트**에서 아래를 실행합니다. Step 2의 개인키 암호를 재입력합니다.

```bash
export AZURE_TENANT_ID='<고객 테넌트 ID>'
export AZURE_CLIENT_ID='<진단 앱의 애플리케이션(클라이언트) ID>'
export AZURE_CLIENT_CERTIFICATE_PATH
read -r -s -p 'Certificate password: ' AZURE_CLIENT_CERTIFICATE_PASSWORD; printf '\n'
export AZURE_CLIENT_CERTIFICATE_PASSWORD
unset AZURE_CLIENT_SECRET AZURE_FEDERATED_TOKEN_FILE

AZURE_CLIENT_CERTIFICATE_PATH="$(python3 scripts/certificate_path.py)" &&
bash scripts/setup.sh verify --certificate-path "$AZURE_CLIENT_CERTIFICATE_PATH" &&
easm-agent collect --setup-file .easm-agent/setup.json \
  --copilot-inventory-file copilot-inventory.json --agent365-registry --output-dir output
```

환경·DLP 파일은 각각 `--admin-evidence-file <파일>`로 전달합니다. 사용하지 않는 선택 옵션은 생략합니다. `collect --copilot-only --tenant-id "<테넌트 ID>" --copilot-inventory-file <파일>`은 Azure·Graph를 호출하지 않습니다.

![Codespaces 점검·수집 완료 예시](docs/imgs/21-codespaces-collection-success.png)

| 실행 폴더의 파일 | 용도 |
| --- | --- |
| `raw-data-<타임스탬프>.json` | 수집 원본·증적·메타데이터 |
| `AI Agent Governance Readiness 진단 결과 보고서 (프로세스·System 통합)_<수집일>.xlsx` | API 26개 항목·수동 입력·증적, 총 18개 시트 |
| 같은 보고서명의 `.pptx` | 27장 요약 보고서. 인터뷰 입력 전에는 잠정본 |

[PPT 템플릿](docs/assessment-report-template.pptx)의 디자인·수동 자료는 유지하며 API 측정값·종속 점수를 갱신합니다. 인터뷰·문서·인용은 API 검증 결과가 아닙니다.

종료 코드는 `0` 정상, `2` 부분 수집·판정 보류입니다. 설정·템플릿·쓰기 오류는 실패로 종료합니다. `NOT_CHECKED`는 대상 없음·프로젝트 미지정이며 수집을 계속합니다. 조회 실패·빈 분모는 0이 아니라 사유와 함께 보존합니다.

### 중요 - 인터뷰 입력 후 PPT 재생성

**인터뷰 54개는 수동 평가입니다.** 기본 [Excel 템플릿](docs/assessment-result-template.xlsx)의 System Evidence는 [API 기준](config/criteria.yaml)의 26개 항목이며 원본 폰트·크기와 노란 입력 셀을 유지합니다.

| 구분 | 입력·결과 위치 |
| --- | --- |
| System Evidence 26개 | `2_SE 원천데이터` F열의 충족 분자·측정 분모, `3_SE 판정`의 결과·근거(자동 반영, 수기 조정 금지) |
| 인터뷰 54개 | `4_프로세스 점수` F열 응답 점수, G/H/I열 문서·시스템·개선 이력 확인, M열 근거 |
| 문서·인용 | `5_문서 실사`, `6_인터뷰 기록` |
| 수집 증적 | 뒤에 추가되는 `8_수집결과 근거`, `8a_수집 Raw 데이터`, `8b_수집이슈 Raw 데이터`, `8c_필드누락사유` |

새 보고서는 수동 예시 대신 빈 입력란을 사용합니다. API 입력은 수기 조정하지 않으며, 미확인·빈 분모는 `N/A`와 사유로 남깁니다.

| 순서 | 작업 |
| --- | --- |
| 1 | 해당 실행의 Excel을 **다운로드**하여 로컬 Excel로 열기 |
| 2 | `4_프로세스 점수` F열에 `1`~`5`, G/H/I에 확인한 증적만 `Y`, M에 근거 입력 |
| 3 | 저장 후 실행 폴더에 **같은 이름으로 덮어쓰기** |
| 4 | 아래 `deck` 명령 실행 후 인터뷰 완료 수·잠정 표시 확인 |

```bash
easm-agent deck --output-dir output --customer "<고객사명>"
```

**`deck`은 Azure에 접속하지 않으며 입력 점수·원본 JSON을 변경하지 않습니다.** 로컬 실행은 JSON·Excel이 있는 폴더를 지정합니다.

- 문서 증적이 없으면 최대 2점, 시스템 증적이 없으면 최대 3점이며 인터뷰 답변만으로는 Level 3 이상을 주지 않습니다.
- 빈칸과 `N/A`는 평균에서 제외하며 0점으로 취급하지 않습니다. 일부만 입력해도 PPT를 만들 수 있고 입력하지 않은 영역은 실측 기준 잠정값입니다.
- 관점 점수는 질문 점수 평균, 영역 점수는 인터뷰 4개 관점 평균입니다. 영역 점수가 System Evidence 점수보다 **1.5점 이상 높으면** System Evidence + 1.0으로 보정하고 "인터뷰-실측 괴리"로 표시합니다. 6개 영역이 모두 확정되어야 종합 점수의 잠정 표시가 없어지며 목표는 Level 3입니다.

## Step 6. <span style="background-color: #e5dcf7; color: #24292f;">[고객/MS 공동]</span> <span style="background-color: #ddf4ff; color: #24292f;">[Codespaces]</span> / <span style="background-color: #ffe8d6; color: #24292f;">[고객 VM]</span> - 결과 검토·정리

| Excel 시트 | 확인할 내용 |
| --- | --- |
| 0_안내 · 1_진단 개요 · 1a_플랫폼 기준 | 진단·라이선스 정보, 플랫폼별 Agent ID와 생성·등록·배포 확인 수. Foundry 생성·등록, Copilot 게시, 이기종 원본 ID 연결을 구분하며 실제 실행 성공을 뜻하지 않음 |
| 2_SE 원천데이터 · 2a_월별 추이 · 2b_세부 내역 | 통합 분자·분모, 생성월·현재 플랫폼 상태·Agent 상세. Azure 비용은 현재 인벤토리 매칭이며 과거 귀속·이기종 비용 아님 |
| 2c_수집 매트릭스 | 항목 × 플랫폼 수집 방식과 측정 범위·미측정 사유 |
| 3_SE 판정 · 3a_단계 신뢰도 | 26개 API 등급·충족률·판정 근거, 단계별 측정 범위·신뢰도·보정 적용 |
| 4_프로세스 점수 · 5_문서 실사 · 6_인터뷰 기록 | 인터뷰 54개 점수·문서 확인·인용 입력 |
| 7_보고서 산출 · 7a_보고서 산출(범위·신뢰도) | 상단 단계별 점수·보정 여부, 하단 보고서 페이지별 대응표(판정과 원천 측정값 분리), 26개 항목의 측정 범위·신뢰도 |
| 8_수집결과 근거 · 8a_수집 Raw 데이터 | 설정·분자·분모, 대상별 판정·직접 증적·적용 기준 출처, 원본 값. 기준 사본·해시·수집기 버전은 결과 JSON에도 보관 |
| 8b_수집이슈 Raw 데이터 · 8c_필드누락사유 | 조회 실패·자료 부족 원인 |

**수집 방식 표기(2c_수집 매트릭스)**

| 표기 | 의미 |
| --- | --- |
| A | API 자동 조회. 승인된 위임 사용자의 API 조회 파일 포함 |
| E | Export. 실제 관리 화면 확인·수동 내보내기 증적 |
| △ | 운영자 확인. 담당자 확인 참고치이며 판정에서 제외 |
| X | 측정 불가. 측정 범위 안이나 조회 실패 |
| 해당 없음 | 플랫폼이 측정 범위 밖이거나 API 필드 미지원. 구체 사유는 비고·근거·JSON에 유지 |

**L5는 API 구성·기록 충족률 100%이며 조직 성숙도·실제 실행 성공이 아닙니다.** 패키지 수·플랫폼 원본 ID·Entra ID의 단위는 [API 참고](docs/api-notes.md#이기종-agent)를 따릅니다.

### 종료 후 정리

- **고객사 VM에서 실행:** Step 4의 `setup.json` 기반으로 생성한 리소스를 정리합니다. 삭제 대상을 먼저 확인합니다.

```bash
bash setup.sh cleanup-plan   # 삭제 대상 조회만
bash setup.sh cleanup-apply  # 진단 앱·SP·해당 역할 할당 삭제, 미사용 진단 역할만 삭제
```

- 역할 삭제 확인이 지연되면 `cleanup-plan` 확인 후 `cleanup-apply`를 재실행합니다. 이미 삭제한 앱·SP는 다시 생성하지 않습니다.

| 담당 | 정리할 항목 | 수행 방법 |
| --- | --- | --- |
| 고객 | 진단 SP의 Azure 역할 할당 | 승인 구독 IAM의 해당 SP 할당을 먼저 회수하고 잔여 여부 확인 |
| 고객 | 진단 앱·SP·등록 인증서·Graph 동의 | Entra → 앱 등록 → `easmagent-diagnostic` → **Delete** 후 엔터프라이즈 애플리케이션에서 잔여 여부 확인 |
| 고객 | Foundry 사용자 지정 역할 정의 | 재사용 계획이 없고 다른 활성·적격 할당도 없을 때만 `EASMAgent Foundry Evidence Reader v2` 삭제 |
| 고객 | 전달 파일·관리자 세션 | ZIP·공개 인증서 정리, CLI 로그아웃, 임시 PIM 종료 |
| MS | 개인키·인증서·암호·경로 기록 | Step 2 인증서 폴더와 .easm-agent/certificate-path 정리, 인증 관련 환경변수 해제 |
| 고객/MS | 보고서·증적·다운로드·공유 사본 | 승인된 보관 기간에 따라 output·evidence·setup.json·공유 사본 폐기. 전용 Codespaces도 불필요하면 삭제 |

## 점검 항목 (System Evidence 26개)

기준은 [criteria.yaml](config/criteria.yaml), 분자·분모·한계는 [점검표](docs/checklist.md)를 따릅니다. 등록부 앱·도구·미귀속 패키지는 Agent로 채점하지 않습니다. OE-SY-18은 완료된 두 스냅샷이 필요하며 첫 수집은 판정 보류입니다.

충족률은 0% L1, 80% 미만 L2, 90% 미만 L3, 100% 미만 L4, 100% L5입니다. ✅는 구현 여부이며 미조회·빈 분모는 `null`입니다. DLP·환경은 별도 관리자 신원으로 읽으며, 데모 원클릭은 [자동 내보내기](demo/README.md#api-샘플-추가와-반복-배포)를 수행합니다. 일반 `collect`에는 Step 5의 증적 파일을 전달합니다.

| 코드 | 영역 | 점검 내용 | 수집 방법 | 수집 |
| --- | --- | --- | --- | --- |
| [DM-SY-01](docs/checklist.md#dm-sy-01) | 1. Demand | Agent 관리 인벤토리 등록·기본정보 완전성 | Agent 365 → Registry → Agent 상세·API 스냅샷 | ✅ |
| [DS-SY-02](docs/checklist.md#ds-sy-02) | 2. Design | 데이터 정책(DLP) 적용 환경 | Power Platform Admin Center → Policies → Data policies | ✅ |
| [DS-SY-03](docs/checklist.md#ds-sy-03) | 2. Design | Agent 등록 출처·플랫폼 유형 식별 | Agent 365 → Registry → Agent 상세·API 스냅샷 | ✅ |
| [DS-SY-04](docs/checklist.md#ds-sy-04) | 2. Design | 플랫폼별 모델·오케스트레이션 구성 | Azure → Model deployments / Copilot 인벤토리 / Agent 365 → 모델 메타데이터 | ✅ |
| [DS-SY-05](docs/checklist.md#ds-sy-05) | 2. Design | 플랫폼별 접근 범위 구성 | Azure → Networking / Copilot 인증·공유 | ✅ |
| [DS-SY-06](docs/checklist.md#ds-sy-06) | 2. Design | 도구 승인·사용자 동의 구성 | Foundry → Tools / Copilot 커넥터 구성 | ✅ |
| [DS-SY-07](docs/checklist.md#ds-sy-07) | 2. Design | 외부 도구·Agent HTTPS 연결 구성 | Foundry → Tools / Agent 365 → Agent endpoint | ✅ |
| [BI-SY-08](docs/checklist.md#bi-sy-08) | 3. Build | Agent 등록·게시·배포 상태 기록 | Agent 365 → Registry → Agent 상세·API 스냅샷 | ✅ |
| [BI-SY-09](docs/checklist.md#bi-sy-09) | 3. Build | 플랫폼별 완료 평가 실행 기록 | Foundry → Evaluation / Copilot 평가 GET·검토 화면 | ✅ |
| [BI-SY-10](docs/checklist.md#bi-sy-10) | 3. Build | Agent 관리자 사용 차단 상태 기록 | Agent 365 → Registry → Agent 상세·API 스냅샷 | ✅ |
| [BI-SY-11](docs/checklist.md#bi-sy-11) | 3. Build | 콘텐츠 필터 정책 연결 | Azure → Microsoft Foundry → Content filters | ✅ |
| [BI-SY-12](docs/checklist.md#bi-sy-12) | 3. Build | 플랫폼별 Agent 버전·게시 기록 | Foundry → Agent versions / Copilot 게시 기록 | ✅ |
| [BI-SY-13](docs/checklist.md#bi-sy-13) | 3. Build | Agent 설명·실행 지침 메타데이터 기록 | Agent 365 → Registry → Agent 상세·API 스냅샷 | ✅ |
| [BI-SY-14](docs/checklist.md#bi-sy-14) | 3. Build | Agent 조직 배포 범위 구성 기록 | Agent 365 → Registry → Agent 상세·API 스냅샷 | ✅ |
| [DP-SY-15](docs/checklist.md#dp-sy-15) | 4. Deploy | 플랫폼별 Agent ID·청사진·원본 연결 | Entra → Agent identities·Blueprints / Copilot 인벤토리 / Agent 365 → 원본 연결 | ✅ |
| [OE-SY-16](docs/checklist.md#oe-sy-16) | 5. Operate | Agent 책임 주체 지정 기록 | Agent 365 → Registry → Agent 상세·API 스냅샷 | ✅ |
| [OE-SY-17](docs/checklist.md#oe-sy-17) | 5. Operate | Agent 허용·배포·공유 대상 구분 | Agent 365 → Registry → Agent 상세·API 스냅샷 | ✅ |
| [OE-SY-18](docs/checklist.md#oe-sy-18) | 5. Operate | Agent 중앙 등록부 변경 이력 추적 | Agent 365 → Registry → Agent 상세·API 스냅샷 | ✅ |
| [OE-SY-19](docs/checklist.md#oe-sy-19) | 5. Operate | 플랫폼별 인증·권한 구성 | Azure → Identity / IAM / Copilot 인벤토리 | ✅ |
| [OE-SY-20](docs/checklist.md#oe-sy-20) | 5. Operate | AI 리소스 활성 경보 범위 | Azure → Monitor → Alerts | ✅ |
| [OE-SY-21](docs/checklist.md#oe-sy-21) | 5. Operate | AI 경보의 작업 그룹·수신자 연결 | Azure → Monitor → Action groups | ✅ |
| [OE-SY-22](docs/checklist.md#oe-sy-22) | 5. Operate | 플랫폼별 지역·보존 구성 정보 | Azure → 위치·보존 / Copilot 관리 환경 지역 / Agent 365 → 원본 리전 | ✅ |
| [OT-SY-23](docs/checklist.md#ot-sy-23) | 6. Optimize | Agent 등록정보 생성·갱신 시각 관리 | Agent 365 → Registry → Agent 상세·API 스냅샷 | ✅ |
| [OT-SY-24](docs/checklist.md#ot-sy-24) | 6. Optimize | AI 비용의 단일 Agent 귀속 | Azure → Cost Management → Cost analysis | ✅ |
| [OT-SY-25](docs/checklist.md#ot-sy-25) | 6. Optimize | AI 민감 데이터 노출 점검 구성 | Azure → Defender for Cloud → Defender plans | ✅ |
| [OT-SY-26](docs/checklist.md#ot-sy-26) | 6. Optimize | 구독 예산·실제·예측 경보 구성 | Azure → Cost Management → Budgets | ✅ |

## 보고서 전용 점검 항목

보조 지표 13개(27~39)는 **26개 등급에 합산하지 않습니다.** [추가 보고서 증적](docs/api-notes.md#추가-보고서-증적)이 없으면 `null`·사유를 남깁니다.

## 개발 참고

| 파일 | 용도 |
| --- | --- |
| [criteria.yaml](config/criteria.yaml) | API 지표·분모·증거·한계·Level 규칙. 설치본에도 기본 기준 포함 |
| [custom-config.yaml](config/custom-config.yaml) | 선택 수집 설정: `workers`·`projects`. 없어도 기본 수집 가능 |
| [고객 권한 설정 ZIP](docs/downloads/customer-setup.zip) | 권한 설정·정리용 4개 파일. 변경 후 `python -m scripts.package_customer_setup`으로 갱신 |
| [Excel 템플릿](docs/assessment-result-template.xlsx) / [PPT 템플릿](docs/assessment-report-template.pptx) | 평가 기준·보고서 서식 |

별도 설정은 `easm-agent collect --criteria <기준.yaml> --config <고객설정.yaml>`로 지정하며, 파일이 없거나 YAML이 잘못되면 오류로 종료합니다. 기준 문장·규칙을 바꿀 때는 `python -m scripts.merge_assessment --source docs/assessment-result-template.xlsx --output <갱신할-템플릿.xlsx>`로 **별도 파일**을 만들어 검토한 뒤 교체합니다. 검사는 `python -m pytest -q`, `python -m ruff check src scripts demo tests`입니다.

<details>
<summary>Excel·PPT 보고서만 다시 만들기</summary>

| 목적 | 명령 |
| --- | --- |
| 원본 JSON에서 Excel·PPT 재생성(수동 입력 보존, Azure 호출 없음) | `easm-agent package --output-dir "<실행 폴더>"` |
| 다른 수동 입력 원본으로 재생성 | `easm-agent package --output-dir "<실행 폴더>" --interview-workbook "<수동 입력 원본.xlsx>"` |
| 수동 입력 원본을 보존하며 새로 수집 | `easm-agent collect --interview-workbook "<수동 입력 원본.xlsx>" --output-dir output` |
| 인터뷰 점수로 PPT만 갱신 | `easm-agent deck --output-dir output --customer "<고객사명>"` |
| PPT 표시값·Excel 셀 매핑 추출 | `easm-agent report-values --workbook "<결과.xlsx>" --output "<새 매핑.json>"` |

기본 대상은 최신 실행 폴더이며 `package`는 새 기준·관리자 증적을 판정에 반영할 때 `--reassess`를 지정합니다.

</details>

<details>
<summary>개발용 데모 실행</summary>

고객 진단에는 필요 없으며 승인된 테스트 환경에서만 실행합니다. AWS·Snowflake 데모는 [이기종 데모 배포](demo/connected-platforms.md)를 따릅니다.

```bash
bash demo/run.sh --apply
bash demo/run.sh --apply --collect
```

첫 명령의 수집은 나중에 수동 실행합니다. 자세한 내용은 [demo/README.md](demo/README.md)를 참고하세요.

</details>
