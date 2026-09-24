# 한국시장 포트 — TAKR6B9D2F

## 기준과 구조

- upstream `refs/tags/v0.5.1^{commit}`: `35543d0248bf89fcb92b17a15858ad0c0e940687`.
- KR 참고 commit: `ce0aa456419800c29325516f984fc55a9a8f14dd`.
- GitHub 정식 fork: <https://github.com/jinsolgpt-dot/TradingAgents-KR-v050>.
- `upstream`은 TauricResearch/TradingAgents, `origin`은 위 개인 fork입니다.
- `codex/korean-market-v050`에서 한국 기능을 관리합니다. 기존 upstream `main`과 commit 이력을 보존합니다.

`tradingagents/dataflows`에 7개 한국 데이터 모듈과 뉴스 결합 어댑터를 추가했습니다.
`tradingagents/markets/korea.py`는 opt-in 설정이고 `cli/korea.py`는 별도 한국 진입점입니다.
기존 설정은 `TRADINGAGENTS_MARKET=KR`이 없으면 원본 동작을 유지합니다.
Codex는 기존 LLM factory의 추가 provider로 연결했습니다. 원본 그래프 구성·에이전트·백테스트
알고리즘을 교체하지 않았습니다. 한국 주식의 회사 정보와 통화 맥락만 그래프에 주입합니다.

주요 접점:

| 원본 접점 | 추가 이유 |
|---|---|
| `dataflows/router.py` | 한국 vendor 등록, 기존 fallback/error 정책 재사용 |
| `dataflows/vendors/yahoo/snapshot.py` | KIS 가격과 검증 snapshot의 출처·원주가 기준 일치 |
| `dataflows/symbols.py`, `date_window.py` | opt-in 한국 종목 정규화·한국 날짜 |
| `default_config.py` | 환경변수 opt-in |
| `graph/trading_graph.py` | Codex 옵션 전달·한국 종목 컨텍스트·공통 오늘 기준 |
| `llm_clients/factory.py`, `validators.py`, `model_catalog.py`, `cli/prompts.py` | provider 선택 |
| `agents/tools.py` | ECOS alias 설명 |
| `pyproject.toml` | `tradingagents-kr` 추가 진입점 |

## 최초 v0.5.0 이식 검증

검증 명령:

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m cli.korea --help
.\.venv\Scripts\python -m cli.korea doctor
git diff --check
```

2026-09-25 Windows / Python 3.10 검증 결과:

- 전체 pytest: **994 passed, 5 skipped, 89 subtests passed** (9.75초).
- KR 전용 테스트 51개 포함. 실제 그래프·Codex 전송 mock·KIS 검증 snapshot·보고서 저장 통과.
- 전체 Ruff: 통과. `git diff --check`: 통과.
- editable 설치 및 설치된 `tradingagents-kr --help`: 통과.
- 생략 5개: Windows에서 POSIX 파일모드 테스트 3개, 미설치 선택 의존성 Bedrock 1개,
  키가 없는 DeepSeek 실제 호출 1개. 기존 provider 모델 경고 등 22개 경고는 남아 있습니다.

upstream의 캐시 테스트 3개는 수정하지 않은 v0.5.0에서도 한국 시간대에 실패했습니다.
`test_ohlcv_cache_freshness.py`의 naive pandas timestamp는 UTC epoch으로 처리되고 실제 캐시는
local timestamp로 읽혀 9시간 차이가 났습니다. fixture의 파일 시각 생성만
`NOW.to_pydatetime().timestamp()`로 보정했습니다. 원본 검증 assertion은 유지했습니다.

KR 테스트는 실제 HTTP와 LLM을 mock합니다. 페이지 처리·API 오류·비밀값 차단·시점 필터,
Codex subprocess 인자와 구조화 응답, 실제 LangGraph/ToolNode 왕복, 한국 보유종목 매칭,
전체 그래프의 보고서·판단 로그 저장까지 검사합니다.
실제 계정 API와 유료 LLM 호출, 실거래는 실행하지 않았습니다.
`doctor` 실행 시 한국 데이터 키 6개는 설정되지 않았고 Codex 실행 파일은 확인됐습니다.

추가 CI `.github/workflows/korea.yml`은 Ubuntu/Windows, Python 3.10/3.12, Asia/Seoul 환경을
검사합니다. 원본 CI는 그대로 유지합니다. 로컬에서 실행하지 않은 CI 환경의 통과를 보장하지 않습니다.

## upstream 업데이트

원격 반영 전에는 현재 변경을 검토하고 별도로 commit/push합니다. 이후 한국 브랜치에서:

```powershell
git fetch upstream --tags
git switch codex/korean-market-v050
# 실제로 존재하는 다음 태그를 확인한 뒤 실행합니다.
git merge refs/tags/<NEW_VERSION>
python -m pytest -q
python -m ruff check .
```

공개된 한국 브랜치의 공유 이력을 유지하려면 merge를 사용합니다. rebase는 협업자와 조율된
비공유 브랜치에서만 선택합니다. 자동 merge나 force push는 설정하지 않았습니다.
수정 충돌은 위 접점 표부터 확인하고, 날짜 주입·가격 출처·structured output 테스트를 유지합니다.

## 알려진 제한

[README.ko.md](../README.ko.md)의 데이터 한계를 참조하세요. 특히 ECOS 과거 빈티지, KIS 과거
재무 snapshot은 지원하지 않습니다. 현재 자료를 과거 자료처럼 반환하지 않습니다.
백테스트 사후 평가 데이터는 원본의 Yahoo 경로를 유지합니다. 분석 가격은 KIS 원주가이므로
기업행위가 있는 기간의 성과 해석에 주의해야 합니다.
KIS를 primary로 선택한 검증 snapshot은 KIS 오류를 드러내며 Yahoo로 조용히 대체하지 않습니다.
v0.5.1의 실행별 ContextVar 설정 격리를 유지합니다. 한국 공급자와 날짜 처리도 실행별
설정을 조회하며, 다른 그래프의 공급자 설정을 덮어쓰는 방식에 의존하지 않습니다.

## v0.5.1 업데이트 — UP5K8M2R7A

2026-09-25 정식 태그 `35543d0248bf89fcb92b17a15858ad0c0e940687`을 merge했습니다.
저장소와 브랜치 이름의 `v050`은 기존 이름이며 설치 패키지 버전은 `0.5.1`입니다.
KIS/DART/ECOS/Naver, 종목 정규화, KST 날짜 처리, Codex 옵션 전달을 새 모듈 경로에 연결했습니다.
상대경로와 옛 private 메서드를 사용하는 한국판 테스트를 새 공개 접점에 맞췄습니다.
원본이 같은 시간대 fixture 문제를 수정했으므로 중복 보정 대신 원본 `_stamp`를 사용합니다.

한국어 보고서에는 영문 역할·팀 제목 옆에 한글을 병기합니다. 영어 출력은 유지합니다.
기존 크래프톤 보고서는 내용을 다시 분석하지 않고 제목만 재생성했으며 원본을 로컬에 보관했습니다.

검증: 전체 pytest **1057 passed, 5 skipped, 92 subtests passed** (22 warnings), Ruff 통과, 보고서 한글/영문 분리·본문 보존 검사, editable 설치 버전 확인.
실제 Codex 구조화 응답과 Naver Cloud 뉴스 조회가 새 버전에서 성공했습니다.
이번 업데이트에서 전체 종목 분석과 모든 외부 API를 다시 실행하지는 않았습니다.
`.env`, `TradingAgents.env`, 생성 보고서는 Git에서 제외하며 푸시 전 실제 키의 staged diff 포함 여부를 검사합니다.

## 출처

- [upstream 기준](https://github.com/TauricResearch/TradingAgents/tree/35543d0248bf89fcb92b17a15858ad0c0e940687)
- [KR 원본](https://github.com/malda231125/TradingAgents-KR/tree/ce0aa456419800c29325516f984fc55a9a8f14dd)
- [Codex 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode)
- [KIS 공식 API 예제](https://github.com/koreainvestment/open-trading-api)
- [OpenDART 개발가이드](https://opendart.fss.or.kr/guide/main.do)
- [ECOS](https://ecos.bok.or.kr/api/)
- [Naver 뉴스 검색](https://api.ncloud-docs.com/docs/naver-api-hub-search-news)

구현에 `karpathy-guidelines`와 `OpenAI Docs`를 적용했습니다. 원본 Apache-2.0 LICENSE를 유지하고
KR 이식 파일에 출처를 명시했습니다. 변경 사유는 루트 NOTICE에도 기록했습니다.
