# 이기종 에이전트 데모 배포

**개발·검증 전용입니다. 고객 운영 워크로드에는 실행하지 않습니다.** 기존 워크로드의 연결·수집은 [고객 설정 가이드](../docs/connected-platforms.md)를 따릅니다.

## 준비

| 대상 | 준비 사항 |
| --- | --- |
| AWS | 비루트 배포 프로필, 서울·도쿄 접근, AgentCore 전용 실행 역할 |
| Snowflake | Cortex 지원 계정, 배포 및 서비스 사용자 생성 권한이 있는 로컬 연결 프로필 |
| 환경 | Python 3.11 이상, AWS CLI 2.32 이상, Bash. Windows는 Git Bash 사용 |

**월 USD 20은 목표이며 과금 상한이 아닙니다.** 기본 구성은 모델 호출·메모리·예약 용량·활동 수집을 사용하지 않습니다.

## AgentCore·Cortex 배포

저장소 루트에서 실행합니다. `--apply`를 생략하면 계정·범위 확인만 수행합니다.

```bash
bash demo/run-connected.sh install
aws login --profile easm-demo --region ap-northeast-2

for region in ap-northeast-2 ap-northeast-1; do
  bash demo/run-connected.sh aws --profile easm-demo \
    --account '<AWS 계정 ID>' --execution-role '<AgentCore 실행 역할 ARN>' \
    --region "$region" --apply || break
done

bash demo/run-connected.sh snowflake --connection '<연결 프로필>' \
  --account '<조직-계정>' --key-directory '<저장소 밖의 RSA 폴더>' --apply
```

| 배포 | 확인할 결과 |
| --- | --- |
| AgentCore | 서울 `EasmSeoulSample`, 도쿄 `EasmTokyoSample`이 `READY`. 기존 동명 Harness는 변경하지 않음 |
| Cortex | `EASM_CONNECTED_DEMO.AGENTS.EASM_CORTEX_SAMPLE`을 `SHOW AGENTS`로 확인 |
| 서비스 사용자 | `EASM_AGENT365_SERVICE`, 역할 `EASM_AGENT365_READER`. 데모 DB·스키마 `USAGE`, Agent `MONITOR`만 부여 |
| RSA | `snowflake-reader.p8` 최초 자동 생성·공개키 등록, 재배포 시 재사용. 등록 키 불일치 시 중단 |

RSA는 저장소 밖에 보관합니다. Windows 기본 폴더는 `%LOCALAPPDATA%\EasmConnectedDemoSnowflake`이며 Azure 인증서와 공유하지 않습니다.

도쿄는 리전 내 Nova Lite, 서울은 [APAC Nova Lite 프로필](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-lite.html)을 사용하므로 모델 호출 시 APAC 내 다른 리전으로 라우팅될 수 있습니다.

## Classic 배포

[Classic 유지 관리 정책](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-classic-maintenance-mode.html)에 따라 최근 12개월 내 사용 이력이 있는 계정에서 신규 생성할 수 있습니다. 별도 `bedrock.amazonaws.com` 실행 역할을 사용합니다.

```bash
bash demo/run-connected.sh aws-classic --profile easm-demo \
  --account '<AWS 계정 ID>' --execution-role '<Classic 실행 역할 ARN>' \
  --region ap-northeast-1 --apply
```

`NOT_PREPARED → PrepareAgent → PREPARED`를 확인합니다. 유지 관리 제한으로 거부되면 중단하며 AgentCore를 Classic으로 표시하지 않습니다.

## 연결·수집 검증

[연결·동기화 절차](../docs/connected-platforms.md#3-agent-365-연결)에 따라 테스트 테넌트에 연결합니다. 입력값은 데모 계정·리전, DB `EASM_CONNECTED_DEMO`, Schema `AGENTS`, User `EASM_AGENT365_SERVICE`입니다. 키는 공식 양식에만 입력합니다.

```bash
bash demo/run-connected.sh collect --setup-file .easm-agent/setup.json --output-dir output
bash demo/run-connected.sh verify 'output/<실행 폴더>' \
  --package-id '<서울 패키지 ID>' --package-id '<도쿄 패키지 ID>' \
  --package-id '<Snowflake 패키지 ID>'
```

실제 패키지 ID로 목록·상세를 대사하며 둘 다 확인되면 종료 0입니다. 이름으로 추정하지 않고 변경 후 재동기화합니다. 미제공 필드는 사유를 유지합니다.
