"""Korean adapters through the unchanged upstream tool/graph contracts."""

from copy import deepcopy
from typing import TypedDict
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from typer.testing import CliRunner

from cli.korea import app
from tradingagents.agents.tools import get_balance_sheet, get_global_news, get_news
from tradingagents.dataflows import korean_news, router as interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import VendorNotConfiguredError
from tradingagents.dataflows.symbols import normalize_symbol
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.settlement import resolve_benchmark
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients.factory import build_llm_kwargs
from tradingagents.markets.korea import get_korea_config, normalize_portfolio
from tradingagents.portfolio import PortfolioContext, Position


def test_korean_sentiment_uses_news_proxy_without_unvalidated_us_social(monkeypatch):
    from tradingagents.agents.analysts import sentiment_analyst
    from tradingagents.dataflows.config import run_config

    prompts = []
    monkeypatch.setattr(sentiment_analyst.get_news, "func", lambda *a: "Naver and DART news evidence")
    def unsupported(*args, **kwargs):
        raise AssertionError("US social should not be fetched for the KR profile")
    monkeypatch.setattr(sentiment_analyst, "fetch_stocktwits_messages", unsupported)
    monkeypatch.setattr(sentiment_analyst, "fetch_reddit_posts", unsupported)

    class LLM:
        def with_structured_output(self, *args, **kwargs):
            raise NotImplementedError

        def invoke(self, messages):
            prompts.extend(messages)
            return AIMessage(content="news-based proxy")

    with run_config(get_korea_config()):
        node = sentiment_analyst.create_sentiment_analyst(LLM())
        result = node({"company_of_interest": "259960.KS", "trade_date": "2026-09-25", "messages": []})
    text = "\n".join(str(m.content) for m in prompts)
    assert "Yahoo Finance" not in text
    assert "Naver and DART news evidence" in text
    assert "unsupported coverage, not neutral sentiment" in text
    assert result["sentiment_report"] == "news-based proxy"


class ToolState(TypedDict):
    messages: list
    trade_date: str


def test_profile_is_opt_in_and_preserves_explicit_overrides():
    original = deepcopy(DEFAULT_CONFIG)
    config = get_korea_config({"tool_vendors": {"get_news": "naver"}, "max_debate_rounds": 3})
    assert original == DEFAULT_CONFIG
    assert config["data_vendors"]["core_stock_apis"] == "kis"
    assert config["tool_vendors"]["get_news"] == "naver"
    assert config["max_debate_rounds"] == 3
    assert config["checkpoint_enabled"] == original["checkpoint_enabled"]


def test_korean_canonical_symbols_and_benchmarks_are_consistent():
    config = get_korea_config()
    set_config(config)
    assert normalize_symbol("삼성전자") == "005930.KS"
    assert normalize_symbol("005930") == "005930.KS"
    assert normalize_symbol("240810") == "240810.KQ"
    assert normalize_symbol("AAPL") == "AAPL"
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = config
    assert resolve_benchmark("삼성전자", config) == "^KS11"
    assert resolve_benchmark("240810.KQ", config) == "^KQ11"
    assert "KRW" in graph.resolve_instrument_context("005930.KS", curr_date="2026-01-05")


def test_upstream_symbol_defaults_are_unchanged():
    assert normalize_symbol("005930") == "005930"
    assert normalize_symbol("BTCUSD") == "BTC-USD"


def test_korean_portfolio_matches_ticker_without_mutating_input():
    original = PortfolioContext(cash=1000000, currency="KRW", positions=[
        Position(ticker="삼성전자", quantity=10, average_price=70000),
        Position(ticker="AAPL", quantity=2),
    ])
    book = normalize_portfolio(original)
    assert "Current position in 005930.KS: 10" in book.render("005930.KS")
    assert "KRW" in book.render("005930.KS")
    assert original.positions[0].ticker == "삼성전자"
    assert book.positions[1].ticker == "AAPL"


@pytest.mark.parametrize("tool,args,method,vendor,expected", [
    (get_news, {"ticker": "005930.KS", "start_date": "2026-01-01", "end_date": "2026-12-31"},
     "get_news", "korea", ("005930.KS", "2026-01-01", "2026-01-05")),
    (get_balance_sheet, {"ticker": "005930.KS", "freq": "quarterly", "curr_date": "2026-12-31"},
     "get_balance_sheet", "dart", ("005930.KS", "quarterly", "2026-01-05")),
    (get_global_news, {"curr_date": "2026-12-31"},
     "get_global_news", "korea", ("2026-01-05", None, None)),
])
def test_toolnode_injects_date_before_korean_vendor(monkeypatch, tool, args, method, vendor, expected):
    set_config(get_korea_config())
    fetch = MagicMock(return_value="verified Korean evidence")
    monkeypatch.setitem(interface.VENDOR_METHODS[method], vendor, fetch)
    builder = StateGraph(ToolState)
    builder.add_node("tools", ToolNode([tool]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    result = builder.compile().invoke({"trade_date": "2026-01-05", "messages": [AIMessage(
        content="", tool_calls=[{"name": method, "args": args, "id": "kr-1", "type": "tool_call"}])
    ]})
    assert result["messages"][0].content == "verified Korean evidence"
    fetch.assert_called_once_with(*expected)


def test_news_contains_disclosures_and_reports_partial_failure(monkeypatch):
    monkeypatch.setattr(korean_news.naver_news, "get_news_naver", lambda *a: "Naver evidence")
    monkeypatch.setattr(korean_news.dart_api, "get_dart_events", lambda *a: "DART evidence")
    assert "DART evidence" in korean_news.get_news("005930", "2026-01-01", "2026-01-05")
    def unavailable(*args):
        raise VendorNotConfiguredError("missing")
    monkeypatch.setattr(korean_news.dart_api, "get_dart_events", unavailable)
    assert "DATA_UNAVAILABLE: DART" in korean_news.get_news("005930", "2026-01-01", "2026-01-05")


def test_cli_reuses_graph_and_portfolio(monkeypatch, tmp_path):
    import tradingagents.graph.trading_graph as graph_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TRADINGAGENTS_LLM_PROVIDER", raising=False)
    fake = MagicMock()
    fake.propagate.return_value = ({"final_trade_decision": "Hold"}, "Hold")
    fake.save_reports.return_value = tmp_path / "report"
    factory = MagicMock(return_value=fake)
    monkeypatch.setattr(graph_module, "TradingAgentsGraph", factory)
    book = tmp_path / "book.json"
    book.write_text('{"currency":"KRW","positions":[{"ticker":"005930","quantity":10}]}')
    result = CliRunner().invoke(app, ["analyze", "삼성전자", "--date", "2026-01-05",
                                     "--portfolio", str(book)])
    assert result.exit_code == 0, result.output
    assert factory.call_args.kwargs["config"]["llm_provider"] == "codex"
    assert fake.propagate.call_args.args == ("005930.KS", "2026-01-05")
    assert fake.propagate.call_args.kwargs["portfolio"].positions[0].ticker == "005930.KS"


def test_cli_rejects_ambiguous_market_before_model_creation(monkeypatch, tmp_path):
    import tradingagents.graph.trading_graph as graph_module

    monkeypatch.chdir(tmp_path)
    factory = MagicMock()
    monkeypatch.setattr(graph_module, "TradingAgentsGraph", factory)
    result = CliRunner().invoke(app, ["analyze", "999999"])
    assert result.exit_code == 1
    factory.assert_not_called()


def test_codex_options_reach_factory():
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = get_korea_config({"llm_provider": "codex", "codex_timeout": 30,
                                     "openai_reasoning_effort": "low"})
    assert build_llm_kwargs(graph.config) == {"codex_timeout": 30, "reasoning_effort": "low"}


def test_verified_snapshot_uses_kis_and_suppresses_short_history(monkeypatch):
    import pandas as pd

    from tradingagents.dataflows import kis_vendor
    from tradingagents.dataflows.vendors.yahoo import snapshot as market_data_validator

    set_config(get_korea_config())
    rows = pd.DataFrame({"Date": ["2026-01-05", "2026-01-06"], "Open": [70000, 999999],
                         "High": [71000, 999999], "Low": [69000, 999999],
                         "Close": [70500, 999999], "Volume": [100, 999999]})
    monkeypatch.setattr(kis_vendor, "get_kis_ohlcv_dataframe", lambda *a: rows)
    def no_yahoo(*args, **kwargs):
        pytest.fail("KIS verification must not query Yahoo")
    monkeypatch.setattr(market_data_validator, "load_ohlcv", no_yahoo)
    report = market_data_validator.build_verified_market_snapshot("005930.KS", "2026-01-05")
    assert "70500" in report and "999999" not in report
    assert "KIS raw/unadjusted KRW" in report
    assert "| close_200_sma | N/A (insufficient history) |" in report


def test_news_for_unmapped_stock_keeps_naver_evidence(monkeypatch):
    monkeypatch.setattr(korean_news.naver_news, "get_news_naver", lambda *a: "Naver evidence")
    result = korean_news.get_news("999999.KQ", "2026-01-01", "2026-01-05")
    assert "Naver evidence" in result and "DATA_UNAVAILABLE: DART" in result


def test_complete_korean_graph_with_codex_transport_mock(monkeypatch, tmp_path):
    """Exercise real graph, Codex schemas/tools, portfolio and report persistence."""
    import json

    import pandas as pd

    from tradingagents.dataflows import kis_vendor
    from tradingagents.llm_clients.codex_client import CodexChatModel

    calls = []

    def sample(schema, root):
        if "$ref" in schema:
            node = root
            for key in schema["$ref"].split("/")[1:]:
                node = node[key]
            return sample(node, root)
        if "enum" in schema:
            return "Hold" if "Hold" in schema["enum"] else schema["enum"][0]
        if "anyOf" in schema:
            return sample(schema["anyOf"][0], root)
        kind = schema.get("type")
        if kind == "object":
            return {key: sample(value, root) for key, value in schema["properties"].items()}
        if kind == "array":
            return []
        if kind in {"number", "integer"}:
            return 0
        if kind == "boolean":
            return False
        if kind == "null":
            return None
        return "한국시장 근거 확인. Rating: Hold"

    def fake_transport(self, prompt, schema):
        calls.append(prompt)
        if schema and "tool_calls" in schema.get("properties", {}):
            if '"role": "tool"' not in prompt:
                return json.dumps({"content": "", "tool_calls": [{
                    "name": "get_verified_market_snapshot", "arguments": json.dumps({
                        "symbol": "005930.KS", "curr_date": "2026-01-05"})}]})
            return json.dumps({"content": "KIS 70500 KRW 확인", "tool_calls": []})
        return json.dumps(sample(schema, schema)) if schema else "한국시장 근거 검토. Rating: Hold"

    monkeypatch.setattr(CodexChatModel, "_call_cli", fake_transport)
    monkeypatch.setattr(kis_vendor, "get_kis_ohlcv_dataframe", lambda *a: pd.DataFrame({
        "Date": ["2026-01-05"], "Open": [70000], "High": [71000], "Low": [69000],
        "Close": [70500], "Volume": [100],
    }))
    config = get_korea_config({"llm_provider": "codex", "quick_think_llm": "mock",
        "deep_think_llm": "mock", "data_cache_dir": str(tmp_path / "cache"),
        "results_dir": str(tmp_path / "results"), "memory_log_path": str(tmp_path / "memory.md")})
    graph = TradingAgentsGraph(selected_analysts=["market"], config=config)
    state, rating = graph.propagate("005930.KS", "2026-01-05", portfolio=PortfolioContext(currency="KRW", cash=1000000))
    assert rating == "Hold"
    assert "KIS 70500 KRW" in state["market_report"]
    assert any("KRW" in prompt and "Portfolio" in prompt for prompt in calls)
    path = graph.save_reports(state, "005930.KS")
    assert path.exists()
    assert path.suffix == ".md" and "KIS 70500 KRW" in path.read_text(encoding="utf-8")
    assert graph.memory_log.load_entries()[0]["ticker"] == "005930.KS"


def test_korean_today_uses_seoul_even_on_utc_host(monkeypatch):
    from datetime import datetime, timezone

    from tradingagents.dataflows import date_window as utils

    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 24, 16, tzinfo=timezone.utc).astimezone(tz)

    set_config(get_korea_config())
    monkeypatch.setattr(utils, "datetime", Clock)
    assert utils.get_current_date() == "2026-09-25"
