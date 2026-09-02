# 팔기전에 - 규제 심사 흐름 프로토타입

상품 상세페이지에서 파싱한 정보를 기준으로 분석 에이전트가 필요한 규제 툴을 선택하고,
툴 결과를 종합한 뒤 검증 에이전트가 최종 결과를 만드는 흐름을 확인하기 위한 프로그램입니다.

현재 외부 API를 직접 호출하지 않습니다. 6개 규제 툴은 결정론적인 Mock 구현이며,
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

Google AI Studio에서 Gemini API 키를 만든 뒤 환경변수로 설정합니다. API 키는 파일이나
명령행 인자에 저장하지 않습니다.

```powershell
$env:GEMINI_API_KEY="발급받은_API_키"
python -m palgijeone.cli --product wireless_rc_helicopter --agent-mode llm
```

LLM 모드는 상품별로 두 번 호출합니다. 분석 에이전트가 6개 규제 툴의 선택 여부와 이유를
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

## 실제 API 연동 지점

각 툴은 동일한 `RegulatoryTool` 인터페이스를 구현합니다. Mock 로직 대신 API 클라이언트를
주입하더라도 반환값은 반드시 `ToolResult`를 유지합니다. 원본 API 응답은 `raw_response`에,
정규화된 판단은 `findings`에 저장합니다. 이를 통해 검증 에이전트가 원본 근거와 판단을
분리해서 확인할 수 있습니다.

> 이 프로토타입의 판단과 법령 문구는 흐름 검증용 예시이며 실제 법률 자문이 아닙니다.
