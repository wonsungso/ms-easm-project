# EASM 거버넌스 진단·수집

EASM(Enterprise Agent Service Management)은 **읽기 전용 API로 Agent 구성·기록을 수집**하고 Excel·PPT 보고서를 만듭니다.

| 구분 | 내용 |
| --- | --- |
| 대상 | Microsoft Foundry(API 조회), Azure 자체 호스팅 Agent(`agent-type: langchain` 태그, `custom-config.yaml` 태그 추가 가능), Entra Agent ID, Microsoft 365 Copilot Agent Builder·Copilot Studio 인벤토리, Agent 365 패키지, Power Platform 관리자 증적 |
| 점검 | API 등급 26개, [추가 보고서 지표 13개(27~39)](#보고서-전용-점검-항목), Copilot·Agent 365 인벤토리. 모델·접근·도구 동의·보안 구성·게시·신원·소유자·인증은 플랫폼별 항목에 포함 |
| 결과 | 실행별 `output/<실행시각-UTC>/`에 Excel·PPT·원본 JSON 저장 |
| 안전 원칙 | 진단 앱은 리소스 변경·배포·삭제·비밀 조회를 하지 않음. 권한 설정·정리는 승인된 관리자가 별도 수행 |

| 필요한 정보 | 문서 |
| --- | --- |
| 고객 준비·수집·결과 확인 | 아래 Step 1~5 |
| 항목별 계산 방식·한계·확인 화면 | [점검 항목 상세](docs/checklist.md) |
| API·권한·평가 계약 | [API 참고](docs/api-notes.md) |
| PPT 작성 규칙 | [PPT 작성 지침](docs/api-notes.md#ppt-작성-지침) |
| 승인된 테스트 환경 배포 | [개발용 데모](demo/README.md) |

## 진행 순서

| 순서 | 담당 | 실행 위치 | 할 일 |
| --- | --- | --- | --- |
| 1 | <span style="background-color: #fff5b1; color: #24292f;">[MS EASM 관리자]</span> | <span style="background-color: #ddf4ff; color: #24292f;">[Codespaces]</span> 터미널 | 인증서 생성, 고객용 ZIP·공개 인증서 전달 |
| 2 | <span style="background-color: #dcffe4; color: #24292f;">[고객사 담당자]</span> | <span style="background-color: #ffe8d6; color: #24292f;">[고객 VM]</span> 브라우저 - Azure Portal | 진단 앱 등록, 공개 인증서 업로드 |
| 3 | <span style="background-color: #dcffe4; color: #24292f;">[고객사 담당자]</span> | <span style="background-color: #ffe8d6; color: #24292f;">[고객 VM]</span> Bash 터미널 | 읽기 권한 설정, `setup.json` 반환 |
| 4 | <span style="background-color: #fff5b1; color: #24292f;">[MS EASM 관리자]</span> | <span style="background-color: #ddf4ff; color: #24292f;">[Codespaces]</span> 터미널·로컬 Excel | 검증·수집, 인터뷰 점수 입력 후 PPT 확정 |
| 5 | <span style="background-color: #e5dcf7; color: #24292f;">[고객/MS 공동]</span> | <span style="background-color: #ddf4ff; color: #24292f;">[Codespaces]</span> / <span style="background-color: #ffe8d6; color: #24292f;">[고객 VM]</span> | 결과 검토, 권한 회수·키·데이터 정리 |

## Step 1. <span style="background-color: #fff5b1; color: #24292f;">[MS EASM 관리자]</span> <span style="background-color: #ddf4ff; color: #24292f;">[Codespaces]</span> - 환경·인증서 준비

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

## Step 2. <span style="background-color: #dcffe4; color: #24292f;">[고객사 담당자]</span> <span style="background-color: #ffe8d6; color: #24292f;">[고객 VM]</span> - 진단 앱 등록

실행 위치: 고객 VM의 브라우저 - Azure Portal.

- **앱 등록:** [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID → 앱 등록 → 새 등록**에서 이름은 `easmagent-diagnostic`, 계정 유형은 **Single tenant**로 등록합니다.

![앱 등록 위치](docs/imgs/07-register-sp.png)

- **ID 확인:** **개요**에서 Tenant ID와 Client ID를 기록합니다. SP 개체 ID는 Step 3 스크립트가 자동 조회합니다.

![앱 ID 확인 위치](docs/imgs/08-sp-overview.png)

- **인증서 등록:** **인증서 및 암호 → 인증서 → 인증서 업로드**에서 받은 `public-cert.pem`을 등록합니다.

![공개 인증서 업로드](docs/imgs/09-upload-certificate.png)

- **MS에 전달:** Tenant ID, Client ID, 승인 구독 ID 목록.

## Step 3. <span style="background-color: #dcffe4; color: #24292f;">[고객사 담당자]</span> <span style="background-color: #ffe8d6; color: #24292f;">[고객 VM]</span> - 읽기 권한 설정

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

**실행 조건:** Python 3.11 이상·Azure CLI가 있는 승인된 Bash 환경, 구독 역할 할당·사용자 지정 역할 생성 권한, Entra 관리자 동의 권한이 필요합니다. **진단 앱에는 Owner·Contributor를 부여하지 않습니다.**

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

- **정상 완료 확인:** 승인 구독 3개 기준으로 Azure 역할 15건·Graph 권한 4건이 `확인됨`이고, 마지막에 `setup.json` 저장 메시지가 나오면 Step 3가 완료된 것입니다.

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

<a id="step-4"></a>

## Step 4. <span style="background-color: #fff5b1; color: #24292f;">[MS EASM 관리자]</span> <span style="background-color: #ddf4ff; color: #24292f;">[Codespaces]</span> - 수집·보고서 확정

| 수집 대상 | 인증·범위 |
| --- | --- |
| Microsoft Foundry·Azure 자체 호스팅 Agent·Entra Agent ID | Step 3의 진단 앱 읽기 권한. 기본 범위는 접근 가능한 활성 구독이며 `setup.json`에 구독을 지정하면 해당 범위 사용 |
| Microsoft 365 Copilot Agent Builder·Copilot Studio | 별도 `Global Reader` 또는 `AI Reader` 사용자의 위임 읽기 내보내기 필요. V1 봇 제외 |
| Agent 365 패키지 | `CopilotPackages.Read.All` 애플리케이션 권한·관리자 동의 및 Agent 365 라이선스(E7 포함 가능) |
| Power Platform 관리 구성(환경·역할·DLP) | 승인된 별도 관리자 읽기 증적. 진단 앱에 관리자 역할을 부여하지 않음 |

### 관리자 위임 읽기 내보내기

Copilot 인벤토리·기존 평가 이력·DLP 정책은 프로젝트가 설치된 승인 관리자 터미널에서 **현재 사용자 권한의 읽기 전용 GET**으로 내보낸 뒤 JSON 파일을 수집 환경으로 전달합니다. `customer-setup.zip`에는 이 도구가 없습니다. 파일로 전달해도 공식 API 조회 원천이면 수집 방식 **A**이며, 실제 관리 화면 확인에 의존한 값만 **E**입니다. 토큰·소유자 ID·사용자 이름·프롬프트·대화는 저장하지 않습니다.

내보내기 전에 대상 테넌트에 로그인합니다.

```powershell
az login --tenant "<테넌트 ID>"
```

| 내보내기 | 명령 | 반영 항목 |
| --- | --- | --- |
| Copilot 인벤토리·기존 평가 | `python scripts\export_copilot_inventory.py --tenant-id "<테넌트 ID>" --output copilot-inventory.json --approved --include-evaluations --evaluation-client-id "<읽기 앱 Client ID>"` | DS-SY-04~06, BI-SY-09·10·12·13, DP-SY-15, OE-SY-19·22 |
| DLP 정책 | `python scripts\export_dlp_policies.py --tenant-id "<테넌트 ID>" --output dlp-policies.json --approved` | DS-SY-02 |

- **기존 평가 이력:** 공식 평가 목록 GET만 사용하며 새 평가를 실행하지 않습니다. 성공한 빈 목록은 평가 0건, 조회 실패는 `null`과 사유입니다. `--evaluation-client-id`를 생략하면 기본 로그인 자격 증명으로 Standard 하니스만 조회합니다.
- **평가 읽기 앱:** 평가 GET에는 Power Platform API의 위임 권한 `CopilotStudio.MakerOperations.Read`가 필요합니다. Azure CLI 앱은 추가 scope 요청이 거부되므로(`AADSTS65002`) 단일 테넌트 공용 클라이언트 앱을 별도로 등록해 **이 위임 권한만** 구성하고, 현재 사용자가 기기 코드로 로그인·동의합니다. 테넌트 전체 동의·비밀·인증서는 필요하지 않으며 진단 앱 권한은 변경하지 않습니다.
- **DLP 정책:** 공식 DLP 정책 목록 조회(`ListPoliciesV2`)로 정책의 적용 환경 범위만 읽고 커넥터 분류·사람 정보는 저장하지 않습니다. 성공한 빈 목록은 정책 0건, 접근 거부·미완료 페이지는 `null`과 사유입니다.
- **실제 화면 증적:** 승인된 검토 화면의 관측은 `--copilot-review-file <검토증적.json>`으로 첨부합니다. 화면의 `No evaluation run`은 BI-SY-09의 평가 0건 근거가 되며, 같은 Agent의 API 결과와 상충하면 판정을 보류합니다. 경고 수·채널 없음은 준비 완료·게시 승인으로 해석하지 않습니다.
- **수집 후 첨부:** 이미 수집한 실행에는 `easm-agent package --output-dir "<실행 폴더>" --admin-evidence-file dlp-policies.json --tenant-id "<테넌트 ID>" --reassess`로 반영합니다. Power Platform 환경·역할 내보내기는 [관리자 읽기 내보내기](docs/api-notes.md#관리자-읽기-내보내기)를 참고합니다.

Agent 365는 기본 권한에 없습니다. 승인된 관리자가 `customer-setup` 폴더에서 `bash setup.sh plan --agent365-reader`로 확인하고 `bash setup.sh apply --agent365-reader`로 적용합니다.

- **준비:** 고객이 반환한 `setup.json`을 저장소의 **.easm-agent/setup.json**으로 저장합니다.
- **실행:** **Step 1에서 사용한 동일 Codespaces 터미널의 저장소 루트**에서 아래를 실행합니다. Step 1의 개인키 암호를 재입력합니다.

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

Copilot 내보내기·DLP 정책·Agent 365를 사용하지 않으면 해당 옵션을 생략합니다. DLP 등 관리자 증적 파일은 `--admin-evidence-file <파일>`로 함께 전달합니다. Copilot 인벤토리만 처리할 때는 `easm-agent collect --copilot-only --tenant-id "<테넌트 ID>" --copilot-inventory-file copilot-inventory.json --output-dir output`을 사용하며 Azure·Graph를 호출하지 않습니다.

![Codespaces 점검·수집 완료 예시](docs/imgs/21-codespaces-collection-success.png)

| 실행 폴더의 파일 | 용도 |
| --- | --- |
| `raw-data-<타임스탬프>.json` | 수집 원본·증적·메타데이터 |
| `report-<타임스탬프>.xlsx` | 통합 템플릿 14개 시트의 SY 26개 실측·인터뷰 입력과 수집 증적 4개 시트(총 18개) |
| `EASM-report-<타임스탬프>.pptx` | 요약 보고서. 인터뷰 입력 전에는 잠정본 |

기본 [PPT 템플릿](docs/assessment-report-template.pptx)은 **비즈니스 연결형 27장**입니다. 원문 설명·제언·인터뷰를 유지하고 System Evidence 26개와 이에 종속된 수준·점수만 갱신합니다. 제공된 인터뷰 점수·문서 제출·인용은 API 검증 결과가 아닙니다. 미관측 실측값은 확인 중으로 남깁니다.

| Working Backwards 실행 | 명령 |
| --- | --- |
| 제공 Excel의 수동 입력 보존 후 수집 | `easm-agent collect --interview-workbook "<수동 입력 원본.xlsx>" --output-dir output` |
| 저장 실측으로 재생성 - Azure 호출 없음 | `easm-agent package --output-dir "<실행 폴더>" --interview-workbook "<수동 입력 원본.xlsx>"` |
| PPT 표시값·Excel 셀 매핑 추출 | `easm-agent report-values --workbook "<결과.xlsx>" --output "<새 매핑.json>"` |

`package`에서 원본을 생략하면 기존 실행 Excel의 수동 입력을 보존합니다. PPT 숫자와 Excel 수식 캐시는 같은 계산 계약을 사용하며 근거 시트에 연결 셀을 기록합니다. 유효한 설정·템플릿과 쓰기 가능한 출력 경로에서 인증·접근 실패가 발생하면 실패 사유와 N/A 26개를 담은 Excel·PPT를 생성하고 종료 코드 2를 반환합니다. 잘못된 설정·손상 템플릿·파일 쓰기 실패는 성공으로 처리하지 않습니다.

`NOT_CHECKED`는 대상 없음·프로젝트 미지정에 따른 미점검이며 수집은 계속됩니다. 권한·인증 실패는 고객 관리자에게 보완을 요청합니다.

| 데이터 | 저장·해석 |
| --- | --- |
| Copilot 인벤토리 | 작성 도구, 환경·Agent ID, 생성·게시 시각, 소유자 존재 여부, 제공된 신원·모델·인증·채널·공유 구성 |
| Agent 365 패키지 | 최근 30일 활동 사용자·세션·실행 시간·예외 건수, 마지막 사용 시각, 분류 메타데이터. 패키지 수는 고유 Agent 수가 아니며 사용자 수를 합산하지 않음 |

미확인 필드·조회 실패·빈 분모는 사유와 함께 보존하고 소유자 ID·사용자 이름·프롬프트·대화는 저장하지 않습니다. 반영 지연·범위·권한·라이선스는 [API 계약과 수집 한계](docs/api-notes.md#선택-agent-365-카탈로그) 및 [개발용 데모](demo/README.md#실제-agent-builder-ui-작성인벤토리-검증)를 참고합니다.

### 중요 - 인터뷰 입력 후 PPT 재생성

**인터뷰 54개는 수동 평가입니다.** 기본 [Excel 템플릿](docs/assessment-result-template.xlsx)은 통합 14개 시트이며 System Evidence는 [API 기준](config/criteria.yaml)의 26개 항목입니다. 원본 폰트·크기와 노란 입력 셀을 유지합니다. 미확인·빈 분모는 공란과 사유를 보존합니다.

| 구분 | 입력·결과 위치 |
| --- | --- |
| System Evidence 26개 | `2_SE 원천데이터` F열의 항목별 충족 분자·측정 분모, `3_SE 판정`의 결과·근거 |
| 원천데이터 표시 | 단위는 `개`, `미국 달러 (USD)` 등으로 표시하며 숫자 원본은 유지. 추출 일시는 `yyyy-mm-dd hh:mm:ss KST`, 추출자는 `EASM 자동화 모듈`. 비고는 짧게 표시하고 상세 근거는 근거 시트에 보존 |
| 인터뷰 54개 | `4_프로세스 점수` F열 응답 점수, G/H/I열 문서·시스템·개선 이력 확인, M열 근거 |
| 문서·인용 | `5_문서 실사`, `6_인터뷰 기록`에 별도 확인 결과 입력 |
| 수집 증적 | 뒤에 추가되는 `8_수집결과 근거`, `8a_수집 Raw 데이터`, `8b_수집이슈 Raw 데이터`, `8c_필드누락사유` 시트 |

템플릿의 수동 작성 예시는 참고용입니다. **새 수집 보고서에는 예시 응답·문서 확인·인용을 복사해 평가하지 않고 입력란을 비웁니다.** API 정보 확인율은 전사 Agent 커버리지나 정책 실효성 신뢰도가 아닙니다. 조회에 성공했으나 대상이 없으면 0, 조회 실패·필수 값 미확인은 공란·`N/A`와 사유로 구분해 0이나 L1로 바꾸지 않습니다.

| 순서 | 작업 | 상세 |
| --- | --- | --- |
| 1 | 다운로드 | 해당 실행의 Excel을 **다운로드**하여 로컬 Excel로 열기 |
| 2 | 질문·기준 확인 | **4_프로세스 점수** C열 코드·D열 문항 및 증적 상한 확인 |
| 3 | 점수 입력 | F열에 `1`~`5` 정수, G/H/I열에 확인한 증적만 `Y`, M열에 근거 입력. 확인 불가는 빈칸 |
| 4 | 업로드 | 저장 후 원래 실행 폴더에 **같은 이름으로 덮어쓰기** |
| 5 | PPT 재생성 | 아래 `deck` 명령으로 Excel 답변 상태·요약과 PPT 갱신 |
| 6 | 최종 확인 | PPT 2번 슬라이드의 인터뷰 완료 수와 3번 슬라이드의 **(잠정)** 표시 확인 |

```bash
easm-agent deck --output-dir output --customer "<고객사명>"
```

로컬에서는 실행 폴더(JSON·Excel)를 내려받아 `--output-dir <실행폴더>`로 재생성할 수 있습니다. **`deck`은 Azure에 접속하지 않으며 입력 점수·원본 JSON을 변경하지 않습니다.**

**입력 규칙**

- 문서 증적이 없으면 최대 2점, 시스템 증적이 없으면 최대 3점이며 인터뷰 답변만으로는 Level 3 이상을 주지 않습니다.
- 빈칸과 `N/A`는 평균에서 제외하며 0점으로 취급하지 않습니다. `3_SE 판정`의 API 등급·원천 입력은 자동 반영되므로 수기 조정하지 않습니다.
- 일부만 입력해도 PPT를 만들 수 있으며 입력하지 않은 영역은 실측 기준 잠정값입니다.

**샘플 인터뷰 응답:** `interview_samples.py`의 샘플을 별도 사본의 `4_프로세스 점수` F/M열에 기입합니다. 이미 작성한 행은 보존하고 문서·시스템·개선 이력을 확인한 것으로 표시하지 않습니다. `--raw-json`을 주면 PPT에 보고서 지표도 반영합니다.

```bash
python -m easm_agent.report_interviews --workbook "<원본.xlsx>" \
  --output-workbook "<기입본.xlsx>" --output-pptx "<기입본.pptx>" \
  --raw-json "<실행폴더>/raw-data-<타임스탬프>.json"
```

**PPT 점수 산정:** 관점 점수는 질문 점수 평균, 영역 점수는 인터뷰 4개 관점 평균입니다. 영역 점수가 System Evidence 점수보다 **1.5점 이상 높으면** System Evidence 점수 + 1.0으로 보정하고 "인터뷰-실측 괴리"로 표시합니다. 인터뷰 또는 System Evidence가 없는 영역은 판정을 보류하고 확인된 쪽만 잠정 표시하며, 6개 영역이 모두 확정되어야 종합 점수의 잠정 표시가 없어집니다. 목표는 Level 3입니다.

**주의:** **인터뷰 입력 후 `package`를 실행하지 마세요.** Excel을 새로 만들어 입력 점수가 사라집니다. 인터뷰 점수는 Excel에만 있으므로 PPT와 함께 보관하고, 다른 위치의 파일로 만들려면 `easm-agent deck --output-dir output --workbook <기입한-xlsx> --customer "<고객사명>"`을 사용합니다.

## Step 5. <span style="background-color: #e5dcf7; color: #24292f;">[고객/MS 공동]</span> <span style="background-color: #ddf4ff; color: #24292f;">[Codespaces]</span> / <span style="background-color: #ffe8d6; color: #24292f;">[고객 VM]</span> - 결과 검토·정리

| Excel 시트 | 확인할 내용 |
| --- | --- |
| 0_안내 · 1_진단 개요 · 1a_플랫폼 기준 | 사용 순서·색상 범례, 진단 기본 정보·라이선스 보유(Y/N)·산정 기준값, 7개 플랫폼별 Agent 수·수집 방식 집계 |
| 2_SE 원천데이터 · 2a_월별 추이 · 2b_세부 내역 | 26개 항목의 분자·분모 원본, 월별 추이, 소유자·권한과 Copilot 게시·채널·대상별 구성 점검. 사용 이력·실제 민감 데이터 노출로 해석하지 않음 |
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
| 해당 없음 | 해당 플랫폼이 항목의 측정 범위 밖. 측정 불가와 별도로 집계 |

**시트 탭 색과 셀 색**

| 구분 | 색 |
| --- | --- |
| 시트 탭 | 0~1a 연두 · 2~3a 초록(System Evidence) · 4~6 연한 파랑(인터뷰) · 7~7a 파랑(종합) |
| 머리글 | 회색 채우기 · 검정 굵게 |
| 입력·참조 값 열 | 노란 채우기 · 파란 글자. 같은 열은 빈 셀·참조 수식도 같은 색 |
| 계산 열 | 흰 바탕 · 검정 글자 |
| 판정·보정·신뢰도 | 연회색 채우기, 판정 단계는 조건부 서식 |
| 합계 행 | 연파랑 채우기 · 굵게 |

**L5는 API 구성·기록 충족률 100%이지 조직 전체의 거버넌스 성숙도를 뜻하지 않습니다.** 검토 후 권한·인증서를 회수하고 키·데이터를 승인된 보관 기간에 따라 정리합니다. 보고서를 재생성해도 관측 시각은 새 실시간 조회로 바꾸지 않습니다.

### 종료 후 정리

- **고객사 VM에서 실행:** Step 3의 `setup.json` 기반으로 생성한 리소스를 정리합니다. 삭제 대상을 먼저 확인합니다.

```bash
bash setup.sh cleanup-plan   # 삭제 대상 조회만
bash setup.sh cleanup-apply  # 진단 앱·SP·해당 역할 할당 삭제, 미사용 진단 역할만 삭제
```

- 역할 삭제 확인이 지연되면 `cleanup-plan` 확인 후 `cleanup-apply`를 재실행합니다. 이미 삭제한 앱·SP는 다시 생성하지 않습니다.

| 담당 | 정리할 항목 | 수행 방법 |
| --- | --- | --- |
| 고객 | 진단 SP의 Azure 역할 할당 | 정리 스크립트가 승인 구독 IAM의 해당 SP 할당을 먼저 회수하고 잔여 여부 확인 |
| 고객 | 진단 앱·SP·등록 인증서·Graph 동의 | Entra → 앱 등록 → `easmagent-diagnostic` → **Delete** 후 엔터프라이즈 애플리케이션에서 잔여 여부 확인 |
| 고객 | Foundry 사용자 지정 역할 정의 | 재사용 계획이 없고 다른 활성·적격 할당도 없을 때만 `EASMAgent Foundry Evidence Reader v2` 삭제 |
| 고객 | 고객 VM의 전달 파일·관리자 세션 | setup.json 전달 후 ZIP·압축 해제 파일·공개 인증서 정리, CLI 로그아웃, 임시 PIM 활성화 종료 |
| MS | 개인키·인증서·암호·경로 기록 | Step 1 인증서 폴더와 .easm-agent/certificate-path 정리, 인증 관련 환경변수 해제 |
| 고객/MS | 보고서·증적·다운로드·공유 사본 | 승인된 보관 기간에 따라 output·evidence·setup.json·공유 사본 폐기. 전용 Codespaces도 불필요하면 삭제 |

## 점검 항목 (System Evidence 26개)

26개 항목 모두 [API 구성·기록 충족률](docs/api-notes.md#심사기준-검토와-점수-반영-2026-11-05)로 평가합니다. ✅는 수집 구현 여부이며 고객 환경의 충족 여부가 아닙니다. 조회 실패·필수 필드 미확인·빈 분모는 **판정 보류(`null`)** 이며 L1·0%가 아닙니다.

| API 구성·기록 충족률 | Level |
| --- | --- |
| 0% | L1 |
| 0% 초과~80% 미만 | L2 |
| 80% 이상~90% 미만 | L3 |
| 90% 이상~100% 미만 | L4 |
| 100% | L5 |

수집 방법은 평가표의 참고 메뉴이며 실제 API 계산 범위와 다를 수 있습니다. 플랫폼별 수집 방식(A·E·△·X)은 Excel `2c_수집 매트릭스`에 표시합니다. Power Platform 3개는 [별도 관리자 읽기 증적](docs/api-notes.md#관리자-읽기-내보내기)이 필요합니다.

| 코드 | 영역 | 점검 내용 | 수집 방법 | 수집 |
| --- | --- | --- | --- | --- |
| [DM-SY-01](docs/checklist.md#dm-sy-01-copilot-studio-제작-권한-보유자-수-및-환경-현황) | 1. Demand | 환경별 역할 할당 기록 | Power Platform Admin Center → Environments → 권한 | ✅ |
| [DS-SY-02](docs/checklist.md#ds-sy-02-커넥터-분류차단-정책데이터-정책-적용-현황) | 2. Design | 데이터 정책 환경 적용 범위 | Power Platform Admin Center → Policies → Data policies | ✅ |
| [DS-SY-03](docs/checklist.md#ds-sy-03-agent-id의-blueprint-연결) | 2. Design | Agent ID의 Blueprint 연결 | Entra → Agents → Agent identities / Blueprints | ✅ |
| [DS-SY-04](docs/checklist.md#ds-sy-04-플랫폼별-모델오케스트레이션-구성) | 2. Design | 플랫폼별 모델·오케스트레이션 구성 | Azure → Model deployments / Copilot 인벤토리 | ✅ |
| [DS-SY-05](docs/checklist.md#ds-sy-05-플랫폼별-접근-범위-구성) | 2. Design | 플랫폼별 접근 범위 구성 | Azure → Networking / Copilot 인증·공유 | ✅ |
| [DS-SY-06](docs/checklist.md#ds-sy-06-도구-승인사용자-동의-구성) | 2. Design | 도구 승인·사용자 동의 구성 | Foundry → Tools / Copilot 커넥터 구성 | ✅ |
| [DS-SY-07](docs/checklist.md#ds-sy-07-외부-도구-https-연결-구성) | 2. Design | 외부 도구 HTTPS 연결 구성 | Microsoft Foundry → Agents → Tools | ✅ |
| [BI-SY-08](docs/checklist.md#bi-sy-08-환경-분리-및-관리형-환경-적용-여부) | 3. Build | 관리형 환경 보호 수준 | Power Platform Admin Center → Environments | ✅ |
| [BI-SY-09](docs/checklist.md#bi-sy-09-플랫폼별-완료-평가-실행-기록) | 3. Build | 플랫폼별 완료 평가 실행 기록 | Foundry → Evaluation / Copilot 평가 GET·검토 화면 | ✅ |
| [BI-SY-10](docs/checklist.md#bi-sy-10-플랫폼별-보안-점검-상태) | 3. Build | 플랫폼별 보안 점검 상태 | Defender → Recommendations / Copilot 위험 구성 | ✅ |
| [BI-SY-11](docs/checklist.md#bi-sy-11-콘텐츠-필터-정책-연결) | 3. Build | 콘텐츠 필터 정책 연결 | Azure → Microsoft Foundry → Content filters | ✅ |
| [BI-SY-12](docs/checklist.md#bi-sy-12-플랫폼별-agent-버전게시-기록) | 3. Build | 플랫폼별 Agent 버전·게시 기록 | Azure → Agent versions·런타임 / Copilot 게시 기록 | ✅ |
| [BI-SY-13](docs/checklist.md#bi-sy-13-플랫폼별-agent-책임자산-메타데이터) | 3. Build | 플랫폼별 Agent 책임·자산 메타데이터 | Foundry → Agent metadata / Azure → Tags / Copilot 인벤토리 | ✅ |
| [BI-SY-14](docs/checklist.md#bi-sy-14-ai-리소스-정책-평가-준수) | 3. Build | AI 리소스 정책 평가 준수 | Azure → Policy → Compliance | ✅ |
| [DP-SY-15](docs/checklist.md#dp-sy-15-플랫폼별-agent-id청사진-연결) | 4. Deploy | 플랫폼별 Agent ID·청사진 연결 | Entra → Agent identities·Blueprints / Copilot 인벤토리 | ✅ |
| [OE-SY-16](docs/checklist.md#oe-sy-16-agent-id-소유자스폰서-연결) | 5. Operate | Agent ID 소유자·스폰서 연결 | Entra → Agents → Owners / Sponsors | ✅ |
| [OE-SY-17](docs/checklist.md#oe-sy-17-agent-id-앱-역할-읽기-범위) | 5. Operate | Agent ID 앱 역할 읽기 범위 | Entra → Agents → Permissions | ✅ |
| [OE-SY-18](docs/checklist.md#oe-sy-18-agent-리소스-실행-로그-연결) | 5. Operate | Agent 리소스 실행 로그 연결 | Azure → Monitor → Diagnostic settings | ✅ |
| [OE-SY-19](docs/checklist.md#oe-sy-19-플랫폼별-인증권한-구성) | 5. Operate | 플랫폼별 인증·권한 구성 | Azure → Identity / IAM / Copilot 인벤토리 | ✅ |
| [OE-SY-20](docs/checklist.md#oe-sy-20-ai-리소스-활성-경보-범위) | 5. Operate | AI 리소스 활성 경보 범위 | Azure → Monitor → Alerts | ✅ |
| [OE-SY-21](docs/checklist.md#oe-sy-21-ai-경보의-작업-그룹수신자-연결) | 5. Operate | AI 경보의 작업 그룹·수신자 연결 | Azure → Monitor → Action groups | ✅ |
| [OE-SY-22](docs/checklist.md#oe-sy-22-플랫폼별-지역보존-구성-정보) | 5. Operate | 플랫폼별 지역·보존 구성 정보 | Azure → 위치·보존 / Copilot 관리 환경 지역 | ✅ |
| [OT-SY-23](docs/checklist.md#ot-sy-23-ai-리소스-사용량-관측-범위) | 6. Optimize | AI 리소스 사용량 관측 범위 | Azure → Monitor → Metrics | ✅ |
| [OT-SY-24](docs/checklist.md#ot-sy-24-ai-비용의-단일-agent-귀속) | 6. Optimize | AI 비용의 단일 Agent 귀속 | Azure → Cost Management → Cost analysis | ✅ |
| [OT-SY-25](docs/checklist.md#ot-sy-25-ai-민감-데이터-노출-점검-구성) | 6. Optimize | AI 민감 데이터 노출 점검 | Azure → Defender for Cloud → Defender plans | ✅ |
| [OT-SY-26](docs/checklist.md#ot-sy-26-구독-예산실제예측-경보-구성) | 6. Optimize | 구독 예산·실제·예측 경보 구성 | Azure → Cost Management → Budgets | ✅ |

## 보고서 전용 점검 항목

원본 보고서의 추가 지표 13개(코드 27~39)입니다. **위 26개 API 등급·점수에 합산하지 않고** 보고서 보조 근거로만 쓰며, 명칭·지표·한계는 [criteria.yaml](config/criteria.yaml)의 `report_items`가 기준입니다. 값이 없으면 0·L1이 아니라 `null`과 사유로 남고 PPT에는 '확인 중' 또는 수집된 유사 지표로 표시합니다. 원천 계약은 [원본 PPT의 추가 증적](docs/api-notes.md#원본-ppt의-추가-증적과-한계)을 따릅니다.

DP-SY-35·DS-SY-36·OE-SY-37의 Copilot 관측값은 각각 BI-SY-12·OE-SY-19·BI-SY-13의 플랫폼별 구성 요소로도 사용합니다. 별도 27~39 코드 점수를 합산하는 것은 아닙니다. 플랫폼별 조건·단위·지원 하니스는 [API 계약](docs/api-notes.md#copilot-인벤토리-읽기-계약-2026-11-19-문서-확인)에 명시합니다.

| 코드 | 영역 | 점검 내용 | 원천 | 수집 방식 |
| --- | --- | --- | --- | --- |
| DM-SY-27 | 1. Demand | 생성·승인 요청의 시간·ID 대사 | 승인 워크플로 | 승인된 추가 증적 파일 |
| DP-SY-28 | 4. Deploy | 독립 등록부와 관측 Agent ID 대사 | 조직 등록부 | 승인된 추가 증적 파일 |
| BI-SY-29 | 3. Build | 동일 버전의 배포 전 완료 평가 기록 | Foundry 평가·배포 기록 | 승인된 추가 증적 파일 |
| OE-SY-30 | 5. Operate | 조건부 접근의 명시적 Agent ID 대상 구성 | Entra 조건부 접근 | 관리자 읽기 내보내기(`export_report_evidence.py`) |
| OE-SY-31 | 5. Operate | 사용자 지정 감사 보존 정책 구성 | Purview 감사 | 승인된 추가 증적 파일 |
| OT-SY-32 | 6. Optimize | Agent별 90일 전체 관측과 미사용 현황 | Agent 단위 사용 이력 | 승인된 추가 증적 파일 |
| OT-SY-33 | 6. Optimize | 고위험 민감 데이터 노출의 조치 상태 | Purview·Defender 발견·조치 | 승인된 추가 증적 파일 |
| OT-SY-34 | 6. Optimize | 월별 실제 비용·귀속 금액 기록 | Azure Cost Management | 자동 수집(`report_cost_history`) |
| DP-SY-35 | 4. Deploy | Copilot 인벤토리 게시 시각 보유 | Power Platform 인벤토리 | Copilot 인벤토리 내보내기 |
| DS-SY-36 | 2. Design | Copilot 인벤토리 인증 방식 구성 | Power Platform 인벤토리 | Copilot 인벤토리 내보내기 |
| OE-SY-37 | 5. Operate | Copilot 인벤토리 소유자 존재 | Power Platform 인벤토리 | Copilot 인벤토리 내보내기 |
| DP-SY-38 | 4. Deploy | 카탈로그 패키지의 게시 요청 승인 상태 | Agent 365 카탈로그 | Agent 365 수집(`--agent365-registry`) |
| OE-SY-39 | 5. Operate | 별도 인사 원천과 Agent 소유자 퇴사 대사 | 인사 대사 결과 | 승인된 추가 증적 파일 |

## 개발 참고

| 파일 | 용도 |
| --- | --- |
| [criteria.yaml](config/criteria.yaml) | API 지표·분모·증거·한계·Level 규칙. 설치본에도 기본 기준 포함 |
| [custom-config.yaml](config/custom-config.yaml) | 선택 수집 설정: `workers`·`tags`·`projects`. 없어도 기본 수집 가능 |
| [고객 권한 설정 ZIP](docs/downloads/customer-setup.zip) | 권한 설정·정리용 4개 파일. 변경 후 `python -m scripts.package_customer_setup`으로 갱신 |
| [Excel 템플릿](docs/assessment-result-template.xlsx) / [PPT 템플릿](docs/assessment-report-template.pptx) | 평가 기준·보고서 서식 |

별도 설정은 `easm-agent collect --criteria <기준.yaml> --config <고객설정.yaml>`로 지정합니다. 명시한 기준 파일이 없거나 YAML이 잘못되면 오류로 종료합니다.

### 자체 Agent 탐지 태그

기본 LangChain 탐지(`agent-type: langchain` 또는 이름의 `langchain`·`lc-agent`)에 `tags`의 **key: value** 조건을 추가할 수 있습니다.

```yaml
# agent-type=custom-agent인 호스트를 기본 탐지 대상에 추가
tags:
  agent-type: custom-agent
```

- `tags`를 비우거나 생략하면 기본 LangChain 탐지만 적용합니다. 여러 key: value는 하나라도 일치하면 추가 탐지(OR)이며 키는 대소문자를 무시하고 값은 정확히 일치해야 합니다.
- 사용자 태그만 일치하면 `custom` 플랫폼의 자체 Agent 후보이며, 기본 조건도 일치하면 LangChain으로 유지합니다. 대상은 승인 구독의 App Service·Container Apps·AKS이며 실행 중인 Agent 코드를 검증하지는 않습니다.
- 메타데이터 태그 기본 이름(`owner`·`sponsor`·`env`·`cost-center`)은 `tag_conventions: {owner_key: service-owner}`로 변경합니다. 과거 `tags` 규약의 문자열 매핑은 `tag_conventions`로 옮깁니다.

### 기준 갱신·개발 검사

- Level 문장·규칙 변경 시 `python -m scripts.merge_assessment --source docs/assessment-result-template.xlsx --output <갱신할-템플릿.xlsx>`로 **별도 파일**을 만들고 검토 후 교체합니다.
- `package`는 저장된 점수를 유지하며 새 기준·관리자 증적을 판정에 반영하려면 `--reassess`를 지정합니다.
- 검사: `python -m pytest -q`, `python -m ruff check src scripts demo tests`

<details>
<summary>Excel·PPT 보고서만 다시 만들기</summary>

- 원본 JSON에서 Excel·PPT 재생성: `easm-agent package --output-dir output`
- 인터뷰 점수를 보존하며 PPT 갱신: `easm-agent deck --output-dir output --customer "<고객사명>"`

기본 대상은 최신 실행 폴더이며 특정 실행 폴더도 지정할 수 있습니다. **`package`는 Excel을 새로 만들므로 인터뷰 입력 후에는 `deck`을 사용합니다.**

</details>

<details>
<summary>개발용 데모 실행</summary>

고객 진단에는 필요 없으며 승인된 테스트 환경에서만 실행합니다.

```bash
bash demo/run.sh --apply
bash demo/run.sh --apply --collect
```

첫 명령의 수집은 나중에 수동 실행합니다. 자세한 내용은 [demo/README.md](demo/README.md)를 참고하세요.

</details>
