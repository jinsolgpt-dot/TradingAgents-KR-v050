"""Report parity: the shared writer produces the report tree for the CLI and the
programmatic API alike (#1037)."""

from types import SimpleNamespace

import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.reporting import write_report_tree


def _state():
    return {
        "market_report": "MKT",
        "news_report": "NEWS",
        "investment_debate_state": {"judge_decision": "RM PLAN"},
        "trader_investment_plan": "TRADE",
        "risk_debate_state": {"judge_decision": "PM DECISION"},
    }


@pytest.mark.unit
def test_write_report_tree_creates_files(tmp_path):
    out = write_report_tree(_state(), "AAPL", tmp_path)
    assert out.name == "complete_report.md"
    assert (tmp_path / "1_analysts" / "market.md").read_text() == "MKT"
    assert (tmp_path / "1_analysts" / "news.md").read_text() == "NEWS"
    assert (tmp_path / "2_research" / "manager.md").read_text() == "RM PLAN"
    assert (tmp_path / "3_trading" / "trader.md").read_text() == "TRADE"
    assert (tmp_path / "5_portfolio" / "decision.md").read_text() == "PM DECISION"
    complete = out.read_text()
    assert "Trading Analysis Report: AAPL" in complete
    assert "MKT" in complete and "PM DECISION" in complete


@pytest.mark.unit
def test_save_reports_explicit_path(tmp_path):
    # Unbound: with an explicit save_path, the method doesn't touch self/config.
    out = TradingAgentsGraph.save_reports(None, _state(), "AAPL", save_path=tmp_path)
    assert (tmp_path / "complete_report.md").exists()
    assert out == tmp_path / "complete_report.md"


@pytest.mark.unit
def test_save_reports_defaults_under_results_dir(tmp_path):
    mock_self = SimpleNamespace(config={"results_dir": str(tmp_path)})
    out = TradingAgentsGraph.save_reports(mock_self, _state(), "AAPL")
    assert out.exists()
    assert out.parent.parent.name == "reports"  # results_dir/reports/AAPL_<stamp>/...
    assert out.parent.name.startswith("AAPL_")


@pytest.mark.unit
def test_korean_report_labels_preserve_body_and_english_default(tmp_path):
    from tradingagents.reporting import KOREAN_REPORT_LABELS

    state = _state()
    state.update(sentiment_report="SENTIMENT", fundamentals_report="FUNDAMENTALS")
    state["investment_debate_state"].update(bull_history="BULL", bear_history="BEAR")
    state["risk_debate_state"].update(aggressive_history="AGGRESSIVE",
                                    conservative_history="CONSERVATIVE", neutral_history="NEUTRAL")
    korean = write_report_tree(state, "259960.KS", tmp_path / "ko", output_language="Korean")
    english = write_report_tree(state, "AAPL", tmp_path / "en")
    ko_text, en_text = korean.read_text(encoding="utf-8"), english.read_text(encoding="utf-8")
    for label, translation in KOREAN_REPORT_LABELS.items():
        assert f"{label} ({translation})" in ko_text
        assert translation not in en_text
    assert (korean.parent / "1_analysts" / "market.md").read_text(encoding="utf-8") == "MKT"


@pytest.mark.unit
def test_graph_report_uses_its_own_language(tmp_path):
    graph = SimpleNamespace(config={"output_language": "Korean"})
    out = TradingAgentsGraph.save_reports(graph, _state(), "259960.KS", save_path=tmp_path)
    assert "Market Analyst (시장·기술 분석가)" in out.read_text(encoding="utf-8")
