"""Korean entry point using upstream analysis and backtesting implementations."""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from dotenv import load_dotenv

app = typer.Typer(help="TradingAgents v0.5.0 한국시장 분석 (주문 기능 없음).")


def _config(provider: str | None, model: str | None) -> dict:
    load_dotenv(Path.cwd() / ".env", override=False)
    from tradingagents.markets.korea import get_korea_config

    selected = provider or os.getenv("TRADINGAGENTS_LLM_PROVIDER", "codex")
    overrides = {"llm_provider": selected}
    if selected == "codex":
        overrides.update(backend_url=None, openai_reasoning_effort=os.getenv(
            "TRADINGAGENTS_OPENAI_REASONING_EFFORT", "low"))
        overrides["codex_timeout"] = float(os.getenv("CODEX_TIMEOUT", "600"))
        if os.getenv("CODEX_COMMAND"):
            overrides["codex_command"] = os.environ["CODEX_COMMAND"]
    for key in ("quick_think_llm", "deep_think_llm"):
        value = model or os.getenv("TRADINGAGENTS_" + key.upper())
        if value or selected == "codex":
            overrides[key] = value or "gpt-6-astra"
    return get_korea_config(overrides)


def _symbol(ticker: str) -> str:
    from tradingagents.dataflows.korea_ticker import canonical_yahoo_symbol

    return canonical_yahoo_symbol(ticker)


def _book(path: Path | None):
    from tradingagents.markets.korea import normalize_portfolio
    from tradingagents.portfolio import load_portfolio

    return normalize_portfolio(load_portfolio(path)) if path else None


@app.command()
def analyze(
    ticker: str = typer.Argument(..., help="회사명, 6자리 코드 또는 .KS/.KQ 심볼"),
    date: str | None = typer.Option(None, "--date", help="YYYY-MM-DD, 기본: 한국 오늘"),
    provider: str | None = typer.Option(None, "--provider"),
    model: str | None = typer.Option(None, "--model"),
    portfolio: Annotated[Path | None, typer.Option("--portfolio", exists=True)] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
):
    """upstream 그래프로 한국어 보고서를 저장합니다."""
    config = _config(provider, model)
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    try:
        symbol, book = _symbol(ticker), _book(portfolio)
        trade_date = date or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        graph = TradingAgentsGraph(config=config)
        state, signal = graph.propagate(symbol, trade_date, portfolio=book)
        destination = graph.save_reports(state, symbol, output)
    except (ValueError, RuntimeError) as exc:
        typer.echo(f"분석 실패 ({type(exc).__name__}). API 설정과 입력을 확인하세요.", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"{symbol} / {trade_date}: {signal}\n보고서: {destination}")


@app.command()
def backtest(
    tickers: str = typer.Argument(..., help="쉼표로 구분한 한국 종목"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    every: int = typer.Option(7, "--every", min=1),
    provider: str | None = typer.Option(None, "--provider"),
    model: str | None = typer.Option(None, "--model"),
    portfolio: Annotated[Path | None, typer.Option("--portfolio", exists=True)] = None,
    run_id: str | None = typer.Option(None, "--run-id"),
):
    """upstream 백테스트·판단 로그·스코어링을 사용합니다."""
    config = _config(provider, model)
    from tradingagents.backtest import iter_grid, run_backtest, summarize
    from tradingagents.decision_log import TradingMemoryLog

    try:
        symbols = [_symbol(t.strip()) for t in tickers.split(",") if t.strip()]
        if not symbols:
            raise ValueError("종목이 필요합니다.")
        result = run_backtest(symbols, iter_grid(start, end, every), config,
                              portfolio=_book(portfolio), run_id=run_id)
    except (ValueError, RuntimeError) as exc:
        typer.echo(f"백테스트 실패 ({type(exc).__name__}). 입력과 설정을 확인하세요.", err=True)
        raise typer.Exit(1) from None
    typer.echo(summarize(TradingMemoryLog({"memory_log_path": str(result.log_path)})).render())
    typer.echo(f"실행 {result.cells_run} / 건너뜀 {result.skipped} / 실패 {len(result.failures)}")
    typer.echo(f"로그: {result.log_path}")
    if result.failures or result.settlement_failures:
        raise typer.Exit(1)


@app.command()
def doctor():
    """API 요청 없이 설치·설정 존재 여부만 확인합니다."""
    config = _config(None, None)
    keys = ("KIS_APP_KEY", "KIS_APP_SECRET", "DART_API_KEY", "ECOS_API_KEY",
            "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET")
    status = {key: bool(os.getenv(key)) for key in keys}
    status["codex_executable"] = bool(shutil.which(os.getenv("CODEX_COMMAND", "codex")))
    status["provider"] = config["llm_provider"]
    typer.echo(json.dumps(status, ensure_ascii=False, indent=2))
    typer.echo("인증·서비스 응답은 검사하지 않았습니다.")


if __name__ == "__main__":
    app()
