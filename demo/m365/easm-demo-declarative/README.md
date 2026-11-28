# M365 선언형 Agent 템플릿

Microsoft 365 Agents Toolkit의 합성 데이터 데모입니다. **Agent Builder UI 작성본과는 작성 출처가 다릅니다.**

## 준비·실행

| 항목 | 조건 |
| --- | --- |
| 개발 도구 | Node.js 22, Microsoft 365 Agents Toolkit 확장 또는 CLI |
| 계정 | 승인된 개발 테넌트·Microsoft 365 Copilot 사용 자격 |
| 실행 | 프로젝트 루트의 [데모 절차](../../README.md#m365-선언형-agentcopilot-studio-코드-데모) 사용 |
| VS Code | `Preview Local in Copilot (Edge/Chrome)` 실행 후 Copilot에서 선택 |

## 파일

| 위치 | 용도 |
| --- | --- |
| [declarativeAgent.json](appPackage/declarativeAgent.json) | 합성 지침·Agent 구성 |
| [manifest.json](appPackage/manifest.json) | 앱 메타데이터 |
| `m365agents.yml` | Toolkit 준비·배포 단계 |
| `.vscode/` | 디버그 설정 |
| `evals/prompts.json` | 합성 평가 예시 |

개인 범위 배포만 사용합니다. 실제 계정·키·테넌트·환경 파일은 커밋하지 않으며 조직 게시·새 로그인·라이선스 구매는 별도 승인 대상입니다.

공식 참고: [선언형 Agent](https://learn.microsoft.com/en-us/plugins/overview-declarative-agent) · [개발 자격](https://learn.microsoft.com/en-us/plugins/prerequisites).
