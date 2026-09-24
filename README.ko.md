# TradingAgents KR — upstream v0.5.0 기반

TauricResearch/TradingAgents **v0.5.0 정식 태그**에 한국시장 데이터와 Codex CLI를 추가한 포크입니다.
원본의 Agent/Graph, point-in-time 날짜 주입, 백테스트, 포트폴리오 컨텍스트,
판단 로그·스코어링·보고서·체크포인트를 유지합니다.

- [원본 v0.5.0](https://github.com/TauricResearch/TradingAgents/tree/v0.5.0)
- [한국 기능 참고 프로젝트](https://github.com/malda231125/TradingAgents-KR/blob/ce0aa456419800c29325516f984fc55a9a8f14dd/README.ko.md)
- [upstream 유지보수·검증 기록](docs/KOREA_PORT.md)
- 원본 영어 설명은 [README.md](README.md)에 유지했습니다.

## 설치와 실행

Python 3.10 이상. 이 저장소는 기존 backtest 프로젝트와 독립적입니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
Copy-Item .env.kr.example .env
```

`.env`에 직접 API 키를 입력합니다. 키·토큰·계좌번호를 소스나 보고서에 넣지 마세요.
이미 `.env`가 있으면 덮어쓰지 말고 필요한 항목만 추가합니다.
Codex CLI는 로그인된 설치를 사용하며 `--ignore-user-config`, `--ephemeral`,
`--output-schema`를 지원하는 버전이 필요합니다.

```powershell
codex login
.\.venv\Scripts\python -m cli.korea doctor
.\.venv\Scripts\python -m cli.korea analyze 삼성전자
.\.venv\Scripts\python -m cli.korea analyze 000660 --date 2026-09-18
```

설치 후 `tradingagents-kr` 명령도 동일하게 사용할 수 있습니다. `doctor`는 변수와
실행 파일의 존재 여부만 보여주며 로그인 성공이나 API 응답을 검증하지 않습니다.
기본은 Codex / `gpt-6-astra` / 추론 `low`이며 `--model` 또는 위 환경변수로 변경합니다.
접근 가능한 모델은 사용자의 Codex 계정에 따릅니다.

다른 기존 provider도 유지됩니다. 예: `analyze 삼성전자 --provider openai --model MODEL_ID`.
해당 provider의 API 키 설정이 별도로 필요합니다.
LLM 모델 입력에 실계좌를 넣지 않아도 분석할 수 있으며 주문 실행 기능은 추가하지 않았습니다.

## 이식 범위

| 기능 | 연결 방식 |
|---|---|
| KIS | 국내 원주가 OHLCV, 페이지 조회, 기술지표, 현재 기업현황·재무비율 |
| DART | 회사코드, 공시 분류·뉴스 결합, 접수일이 확인되는 재무제표 |
| ECOS | 기준금리, 원/달러, CPI, KOSPI, M2 |
| Naver News | 한국시간 게시일 필터, 최대 1,000건 검색 범위 |
| 한국 종목 resolver | 회사명·코드·명시적 `.KS`/`.KQ`, 32개 주요 종목 오프라인 사전 |
| Codex CLI | LangChain 도구 호출·구조화 응답·콜백, stdin·timeout·격리 작업폴더 |

KIS는 가격과 검증 snapshot을 같은 원주가 기준으로 사용합니다. API 주문·계좌 조회는 없습니다.
공시와 뉴스는 하나의 기존 `get_news` 도구에서 제공하고, 한쪽이 불가능하면 출처별로 표시합니다.
일반 공시를 내부자 거래 데이터로 대신 표시하지 않습니다.

회사명은 유일하게 해석될 때만 사용합니다. 시장이 확인되지 않는 코드는 `.KS`(KOSPI) 또는
`.KQ`(KOSDAQ)를 직접 지정해야 하며, 시장을 임의로 추측하지 않습니다.
전체 DART 회사명 사전은 `DART_API_KEY`를 설정한 뒤 다음 코드로 갱신할 수 있습니다.
이 사전에는 거래소 구분이 없어 신규 종목은 여전히 suffix를 지정해야 할 수 있습니다.

```python
from dotenv import load_dotenv
load_dotenv(override=False)
from tradingagents.dataflows.korea_ticker import update_from_dart
print(update_from_dart())
```

## 포트폴리오와 백테스트

upstream 포트폴리오 JSON을 그대로 사용합니다. 한국 진입점이 종목 코드를 정규화합니다.

```json
{"cash": 1000000, "currency": "KRW", "positions": [
  {"ticker": "005930", "quantity": 10, "average_price": 70000}
]}
```

```powershell
python -m cli.korea analyze 삼성전자 --portfolio portfolio.json
python -m cli.korea backtest 005930,000660 --start 2026-01-05 --end 2026-02-02 --every 7 --run-id kr-example
```

백테스트는 원본의 **판단 결과 평가**입니다. 주문·수수료·포트폴리오 수익곡선 시뮬레이터가 아닙니다.
각 날짜·종목에서 LLM 호출이 발생합니다. `--run-id`를 재사용하면 기록된 cell은 건너뜁니다.
KOSPI는 `^KS11`, KOSDAQ은 `^KQ11`을 벤치마크로 설정하며 사후 수익률 평가는 원본처럼 Yahoo를 사용합니다.
포트폴리오 파일은 날짜 전체에서 동일하게 적용되므로 해당 날짜 당시의 보유 내역인지 확인해야 합니다.

Python API:

```python
from dotenv import load_dotenv
load_dotenv(override=False)
from tradingagents.markets.korea import get_korea_config, normalize_portfolio
from tradingagents.dataflows.korea_ticker import canonical_yahoo_symbol
from tradingagents.graph.trading_graph import TradingAgentsGraph

config = get_korea_config({"llm_provider": "codex", "quick_think_llm": "gpt-6-astra",
                          "deep_think_llm": "gpt-6-astra", "openai_reasoning_effort": "low"})
graph = TradingAgentsGraph(config=config)
symbol = canonical_yahoo_symbol("삼성전자")
state, signal = graph.propagate(symbol, "2026-09-18")
graph.save_reports(state, symbol)
```

## 과거 시점 데이터의 한계

- KIS 기업현황·재무비율과 ECOS 수정 통계는 과거 빈티지를 제공하지 않아 과거 분석에서
  `DATA_UNAVAILABLE`로 반환합니다. 관측월을 공표일로 오인하지 않습니다.
- DART는 재무제표의 접수번호 날짜가 분석일 이하인 행만 사용합니다. 현재 API가 반환한
  정정본이 더 늦게 접수됐다면 이를 제외하며, 원본 과거 문서를 복원하는 아카이브는 아닙니다.
  최근 3개 사업연도를 탐색합니다. 연간/누적 현금흐름을 단독 분기로 재해석하지 않습니다.
- Naver 검색은 완전한 과거 뉴스 아카이브가 아닙니다. 게시일 없는 자료와 미래 기사는 제외합니다.
- KIS 원주가는 분할·병합 시 불연속이 생깁니다. 자동 기업행위 보정은 포함하지 않았습니다.
  오래된 마지막 봉은 upstream의 10일 기준으로 거부합니다. 정밀 거래일 달력 검증은 별도입니다.
- 과거 시점 차단은 공급 자료와 도구에 적용됩니다. LLM 자체의 학습 지식까지 과거로 되돌리지는 못합니다.
- 실제 API·Codex 로그인 실행은 사용자 환경에서 확인해야 합니다. 검증 결과와 미실행 항목은
  [검증 기록](docs/KOREA_PORT.md)에 구분해 기재합니다.

## 키 발급 및 문서

[KIS](https://apiportal.koreainvestment.com/), [OpenDART](https://opendart.fss.or.kr/),
[ECOS](https://ecos.bok.or.kr/api/), [Naver](https://api.ncloud-docs.com/docs/naver-api-hub-search-news),
[Codex 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode).

Apache-2.0. 원본 LICENSE를 유지하며 이식 출처와 수정사항은 [NOTICE](NOTICE)에 기록했습니다.
