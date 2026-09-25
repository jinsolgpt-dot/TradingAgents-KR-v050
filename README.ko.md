# TradingAgents KR — upstream v0.5.1 기반

TauricResearch/TradingAgents **v0.5.1 정식 태그**에 한국시장 데이터와 Codex CLI를 추가한 포크입니다.
원본의 Agent/Graph, point-in-time 날짜 주입, 백테스트, 포트폴리오 컨텍스트,
판단 로그·스코어링·보고서·체크포인트를 유지합니다.

- [원본 v0.5.1](https://github.com/TauricResearch/TradingAgents/tree/v0.5.1)
- [한국 기능 참고 프로젝트](https://github.com/malda231125/TradingAgents-KR/blob/ce0aa456419800c29325516f984fc55a9a8f14dd/README.ko.md)
- [upstream 유지보수·검증 기록](docs/KOREA_PORT.md)
- [재무 기간·뉴스 장애·보고서 오류 수정 기록](docs/REPORT_AUDIT_RP8K4M2D7A.md)
- 원본 영어 설명은 [README.md](README.md)에 유지했습니다.

원본 전체 기능과 한국판의 차이는 [원본 기능 안내](docs/UPSTREAM_FEATURES.ko.md)를 참고하세요.

## 처음 사용하는 분을 위한 사용 순서

이 프로그램은 종목의 시세·재무·뉴스를 AI 분석가들이 검토하고, 상승·하락 의견과
위험 검토를 거쳐 판단 보고서를 만드는 도구입니다. 주식 주문을 실행하지 않습니다.
한국시장 CLI에는 `analyze`(종목 분석), `backtest`(과거 판단 평가),
`doctor`(설정 존재 여부 확인) 세 가지 명령이 있습니다.

### Codex 앱에서 요청하기

Codex 앱에서 이 프로젝트 폴더를 작업 대상으로 열고 다음처럼 요청합니다.
다른 프로젝트의 대화에서는 TradingAgents 프로젝트 경로도 함께 알려주세요.

> TradingAgents로 삼성전자를 오늘 기준으로 실제 분석 실행해줘.
> 보고서를 저장하고 최종 판단, 근거, 주요 위험, 누락된 자료를 설명해줘.

> TradingAgents로 삼성전자와 SK하이닉스를 각각 분석한 뒤 두 보고서를 비교해줘.

> 삼성전자 10주를 평균 7만 원에 보유했고 현금은 100만 원이야.
> 이 보유 내역을 포트폴리오 파일로 만들어 TradingAgents 분석에 반영해줘.

이는 Codex에게 프로그램 실행을 요청하는 예시입니다. 비교 전용 CLI 명령은 없으므로
여러 종목 비교는 각각 실행한 결과를 비교합니다. 채팅 답변만 받는 것과 실제 프로그램을
실행하는 것은 다르므로 실행 여부와 생성된 보고서 경로를 확인하세요.
이미 연결을 마친 PC에서는 매번 CLI 로그인이나 CMD 창 열기를 할 필요가 없습니다.

### PowerShell에서 직접 첫 분석 실행하기

아래 경로는 이 프로젝트를 설치한 현재 PC 기준입니다. 다른 PC에서는 저장소 경로로 바꾸세요.
이후의 모든 명령은 저장소 폴더에서 실행합니다. 가상환경 Python을 직접 지정하므로
별도의 가상환경 활성화 명령은 필요하지 않습니다.

```powershell
cd C:\Users\wlsth\Documents\TradingAgents-KR-v050
.\.venv\Scripts\python -m cli.korea doctor
.\.venv\Scripts\python -m cli.korea analyze 삼성전자 --output .\reports\samsung-first
```

`doctor`의 `true`는 설정이 있다는 의미이며 서버 인증 성공을 뜻하지 않습니다.
`analyze`는 데이터를 조회하고 여러 차례 모델을 호출하므로 단순 질의보다 오래 걸릴 수 있습니다.
완료하면 종목·분석일·판단과 보고서 경로를 출력합니다.

### 보고서 열고 읽기

위 명령의 종합 보고서는 `reports/samsung-first/complete_report.md`입니다.
Codex에 “생성된 complete_report.md를 열고 설명해줘”라고 요청하거나 다음처럼 열 수 있습니다.

```powershell
notepad .\reports\samsung-first\complete_report.md
```

| 파일·폴더 | 확인할 내용 |
|---|---|
| `complete_report.md` | 분석·토론·판단을 합친 종합 보고서 |
| `1_analysts/` | 시장, 심리, 뉴스, 재무 분석 |
| `2_research/` | 상승·하락 논거와 연구 담당자의 결론 |
| `3_trading/trader.md` | 트레이더의 제안 |
| `4_risk/` | 공격적·보수적·중립적 관점의 위험 검토 |
| `5_portfolio/decision.md` | 최종 포트폴리오 담당자의 판단 |

각 파일은 해당 결과가 생성된 경우에만 저장됩니다.
한국어 출력에서는 `Market Analyst (시장·기술 분석가)`처럼 역할·팀 제목을 한글과 병기합니다.
최종 판단을 먼저 읽고, 그 판단에 사용한 자료의 날짜·출처와 `DATA_UNAVAILABLE` 표시를 확인하세요.
자료가 없다는 표시를 해당 기업에 문제가 없다는 뜻으로 해석하면 안 됩니다.
`--output`은 파일명이 아닌 **폴더 경로**입니다. 같은 경로를 재사용하면 기존 보고서를
덮어쓰므로 분석을 보관하려면 실행마다 다른 폴더명을 사용하세요.
생략하면 설정된 `results_dir` 아래 `reports/종목_실행시각/`에 저장됩니다.

## 기능별 실전 예시

### 종목 및 과거 날짜 지정

```powershell
# 종목코드로 오늘 분석 (기본 날짜는 한국시간 기준)
.\.venv\Scripts\python -m cli.korea analyze 000660 --output .\reports\hynix-first

# 과거 특정 날짜 기준 분석
.\.venv\Scripts\python -m cli.korea analyze 005930 --date 2026-09-18 --output .\reports\samsung-20260918

# 시장을 명시: .KS는 코스피, .KQ는 코스닥
.\.venv\Scripts\python -m cli.korea analyze 240810.KQ
```

미래 날짜는 사용하지 마세요. 과거 분석은 아래의 ‘과거 시점 데이터의 한계’가 적용됩니다.
회사명 해석에 실패하면 정확한 종목코드와 시장 suffix를 지정합니다.

### 보유 내역 반영

저장소 폴더에 `portfolio.json`을 만들고 아래 내용을 저장합니다.
실제 계좌 연결 없이 사용자가 입력한 수량·평균매입가·현금을 판단에 전달합니다.

```json
{
  "cash": 1000000,
  "currency": "KRW",
  "positions": [
    {"ticker": "005930", "quantity": 10, "average_price": 70000}
  ]
}
```

```powershell
.\.venv\Scripts\python -m cli.korea analyze 삼성전자 --portfolio .\portfolio.json --output .\reports\samsung-held
```

`cash`는 사용 가능한 현금, `quantity`는 주식 수, `average_price`는 주당 평균매입가입니다.
다른 보유 종목은 `positions` 배열에 추가합니다. 실행 후 보유 수량이 자동 갱신되지는 않습니다.

### 소규모 백테스트와 결과 해석

처음에는 한 종목·두 날짜로 시작하세요. 아래 예시는 9월 1일과 8일 두 번 분석합니다.
`--every 7`은 **달력상 7일 간격**이며 7거래일 간격이 아닙니다.

```powershell
.\.venv\Scripts\python -m cli.korea backtest 005930 --start 2026-09-01 --end 2026-09-08 --every 7 --run-id samsung-trial-01
```

| 출력 | 의미 |
|---|---|
| `Resolved cells` | 사후 결과가 확정된 종목·날짜 조합 수 |
| `pending` | 아직 사후 평가가 확정되지 않은 조합 수 |
| `unscored` | 점수를 계산하지 못한 조합 수 |
| `n` | 해당 판단 등급에서 평가한 표본 수 |
| `called the direction` | 벤치마크 대비 초과수익 방향을 맞힌 비율 |
| `mean alpha` | 해당 판단들의 평균 벤치마크 대비 초과수익률 |
| 실행·건너뜀·실패 | 이번 실행의 진행 결과 |
| 로그 | 판단 기록이 저장된 파일 경로 |

보유(Hold)는 방향을 주장하지 않으므로 방향 적중률이 없습니다. 초과수익률은 계좌 수익률이
아니며 매도 판단이라고 수익률 부호가 매매 손익으로 자동 변환되는 것도 아닙니다.
미확정 결과는 적중률에 포함되지 않습니다.

중단 후 이어서 실행하려면 **같은 명령과 같은 `--run-id`**를 사용합니다.
설정·모델·포트폴리오를 바꾼 새 실험은 새 run-id를 사용해 이전 결과와 섞지 마세요.
두 종목은 `005930,000660`처럼 쉼표로 구분합니다. 종목 수와 분석 날짜 수만큼 모델 호출이
늘어납니다. 백테스트에는 주문 체결, 수수료, 현금 잔고 변화, 계좌 수익곡선 계산이 없습니다.

### 자주 만나는 문제

| 상황 | 확인할 것 |
|---|---|
| `No module named cli.korea` | 저장소 폴더인지, `.venv`의 Python을 쓰는지 확인 |
| `doctor`에서 키가 `false` | 저장소의 `.env`에 필요한 변수가 있는지 확인 |
| `doctor`는 정상인데 분석 실패 | 실제 API 인증·권한, Codex 로그인·모델 접근 여부를 별도로 확인 |
| Naver 인증 실패 | Naver Cloud **NAVER API HUB**의 키인지 확인. Naver Developers 키와 호출 방식이 다름 |
| Codex가 새 버전을 요구 | 사용 중인 CLI 버전과 `.env`의 `CODEX_COMMAND` 경로 확인 |
| `DATA_UNAVAILABLE` | 자료 누락·과거 시점 제한을 확인. 정상 데이터로 간주하지 않음 |
| 종목명 인식 실패 | 정확한 코드와 `.KS` 또는 `.KQ`를 지정 |

현재 CLI는 실행 폴더의 `.env`를 읽습니다. 별도로 보관한 `TradingAgents.env`를 수정하는
것만으로 실행 설정이 바뀌지는 않으므로 프로젝트 `.env`에도 반영해야 합니다.
`.env`와 `*.env`는 Git에서 제외합니다. 예제 파일에는 실제 키를 넣지 마세요.

옵션 전체는 다음 명령으로 확인할 수 있습니다.

```powershell
.\.venv\Scripts\python -m cli.korea analyze --help
.\.venv\Scripts\python -m cli.korea backtest --help
```

## 새 PC에 설치하기

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
