# 팔기전에 - 규제 심사 흐름 프로토타입

상품 상세페이지에서 파싱한 정보를 기준으로 분석 에이전트가 필요한 규제 툴을 선택하고,
툴 결과를 종합한 뒤 검증 에이전트가 최종 결과를 만드는 흐름을 확인하기 위한 프로그램입니다.

현재 규제 기관의 외부 API를 직접 호출하지 않습니다. 6개 규제 툴은 결정론적인 Mock 구현이며,
각 툴의 `run()` 내부를 관세청·식약처·법제처 API 어댑터로 교체할 수 있도록 분리했습니다.

## 전체 흐름

```text
테스트 상품(Product)
  -> 분석 에이전트가 툴 선택
  -> 6개 툴 실행(선택되지 않은 툴도 not_applicable로 기록)
  -> 결과 종합 툴(DraftAssessment)
  -> 검증 에이전트(VerificationResult)
  -> 최종 결과(FinalAssessment)
```

## 스키마 버전

- `v0.1-flow` 태그: 모든 툴이 공통 `ToolResult`와 `RegulatoryFinding`만 반환하는 기준 버전
- `feat/typed-tool-results` 브랜치: 공통 결과 안에 6개 툴별 전용 `result` 스키마를 추가한 v0.2
- `examples/v0_1_generic_result.json`, `examples/v0_2_typed_tool_result.json`: 두 형식의 비교 예시
- `examples/v0_3_retry_flow.json`: 검증 후 통관 툴을 재호출한 흐름 예시

v0.2에서도 공통 `findings`는 유지합니다. `result`는 툴별 구조화 결과, `findings`는
종합·검증 단계에서 공통으로 사용하는 판단, `raw_response`는 외부 API 원본 응답입니다.
최종 `FinalAssessment`에도 6개의 `tool_results`를 보존해 판단 근거를 역추적할 수 있습니다.

### 검증 후 재검사 루프(v0.3)

`feat/verification-retry-loop` 브랜치에서는 검증 결과가 `revision_required`일 때
`additional_tools_required`, 실패한 툴, critical 이슈와 연결된 finding을 기준으로 필요한 툴만
재호출합니다. 이후 결과를 다시 종합하고 검증하며 기본 최대 재검사 횟수는 2회입니다.

`user_input_required`는 자동 재검사하지 않습니다. 사용자의 답변이 필요한 상태이므로
`incomplete` 최종 결과와 질문을 반환합니다. 모든 재호출 결과는 `tool_result_history`와
`remediation_history`에 보존됩니다.

추가 툴 요청이 남아 있으면 critical 이슈 유무와 관계없이 재검사합니다. 검증 응답의
finding 참조가 현재 초안과 맞지 않거나 검증 호출 자체가 실패하면, 규제 툴을 무작정
재실행하지 않고 `incomplete`로 종료합니다. 실패 이유는 검증 이슈와 trace에,
각 회차의 검증 결과는 `verification_history`에 남습니다. SDK 예외 메시지 원문은
키나 요청 데이터가 노출되지 않도록 결과에 포함하지 않습니다.

현재 루프는 같은 상품으로 툴을 재호출합니다. 일시적 오류나 누락된 툴 실행은 처리하지만,
새 정보 수집이나 판정 로직 수정까지 자동으로 수행하지는 않습니다.

## 실행

Python 3.11 이상을 권장합니다.

```bash
python -m pip install -r requirements.txt
python -m palgijeone.cli --list
python -m palgijeone.cli --product wireless_rc_helicopter
python -m palgijeone.cli --all
python -m palgijeone.cli --product cosmetic_serum --json
```

### Gemini LLM 에이전트 모드

Google AI Studio에서 Gemini API 키를 만든 뒤 저장소 루트의 `.env`에 입력합니다.
파일이 없다면 `.env.example`을 기준으로 만듭니다. `.env`와 `.env.*`는 Git에서
제외되며 빈 키 템플릿인 `.env.example`만 공유합니다. 실제 키를 커밋하거나 채팅에 올리지 마세요.

```dotenv
GEMINI_API_KEY=발급받은_API_키
```

LLM 클라이언트가 실행 위치에 관계없이 저장소 루트의 `.env`를 자동으로 읽습니다.
이미 설정된 환경변수가 `.env`보다 우선하며, 코드에서 명시한 `api_key`는 둘보다 우선합니다.

```powershell
python -m pip install -r requirements.txt
python -m palgijeone.cli --product wireless_rc_helicopter --agent-mode llm
```

LLM 모드는 최초 분석과 검증에 두 번, 재검사마다 추가 검증에 한 번씩 호출합니다.
기본 재검사 한도 2회일 때 정상 응답 기준 최대 4회입니다. 분석 에이전트가 6개 규제 툴의 선택 여부와 이유를
구조화 응답으로 만들고, 규칙 기반 툴 실행 후 검증 에이전트가 결과의 누락·모순·근거를 다시
검토합니다. `--model`로 모델을 바꿀 수 있으며 기본값은 `gemini-2.5-flash-lite`입니다.

```powershell
python -m palgijeone.cli --product cosmetic_serum --agent-mode llm --json
```

무료 구간의 요청 한도와 데이터 처리 정책은 Gemini API 정책을 따릅니다. 실제 상품 정보나
민감한 데이터 대신 테스트 상품으로 먼저 실행하는 것을 권장합니다.

프로젝트 루트에서 바로 실행할 수 있도록 루트의 `palgijeone` 패키지를 사용합니다.

## 테스트

```bash
python -m unittest discover -s tests -v
```

## 주요 파일

- `palgijeone/schemas.py`: 상품, 툴 결과, 종합 결과, 검증 및 최종 스키마
- `palgijeone/sample_products.py`: 테스트 상품 데이터
- `palgijeone/regulatory_tools.py`: 6개 Mock 규제 툴
- `palgijeone/selector.py`: 상품 정보 기반 툴 선택 규칙
- `palgijeone/aggregator.py`: 6개 툴 결과 종합
- `palgijeone/verifier.py`: 검증 에이전트
- `palgijeone/pipeline.py`: 전체 오케스트레이션 및 실행 추적
- `palgijeone/cli.py`: 흐름 확인용 CLI

## 처음 코드를 읽는 순서

1. `schemas.py`에서 `Product → ToolResult → DraftAssessment → FinalAssessment` 데이터 흐름 확인
2. `selector.py`에서 상품 신호가 6개 툴 선택으로 변환되는 규칙 확인
3. `regulatory_tools.py`에서 툴별 상세 `result`와 공통 `findings` 생성 과정 확인
4. `aggregator.py`와 `verifier.py`에서 종합·검증 조건 확인
5. `pipeline.py`에서 `revision_required` 이후 선택적 재검사 루프 확인
6. `llm_agents.py`에서 규칙 기반 컴포넌트를 Gemini 에이전트로 교체하는 방식 확인

주석은 코드가 무엇을 하는지 반복하기보다 스키마 분리 이유, 감사 가능성, 재검사 종료 조건처럼
처음 보는 사람이 의도를 파악하기 어려운 지점을 중심으로 작성했습니다.

## 실제 API 연동 지점

각 툴은 동일한 `RegulatoryTool` 인터페이스를 구현합니다. Mock 로직 대신 API 클라이언트를
주입하더라도 반환값은 반드시 `ToolResult`를 유지합니다. 원본 API 응답은 `raw_response`에,
정규화된 판단은 `findings`에 저장합니다. 이를 통해 검증 에이전트가 원본 근거와 판단을
분리해서 확인할 수 있습니다.

> 이 프로토타입의 판단과 법령 문구는 흐름 검증용 예시이며 실제 법률 자문이 아닙니다.
