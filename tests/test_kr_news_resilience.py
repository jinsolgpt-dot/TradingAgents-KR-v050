"""Network faults must be explicit missing evidence, not a graph failure."""
from unittest.mock import Mock

import pytest
import requests
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tests.test_kr_integration import ToolState
from tradingagents.agents.tools import get_global_news
from tradingagents.dataflows import korean_news, naver_news, router
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import VendorRateLimitError, VendorUnavailableError
from tradingagents.markets.korea import get_korea_config


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setattr(naver_news.time, "sleep", lambda _: None)
    monkeypatch.setenv("NAVER_CLIENT_ID", "test-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "SECRET")


def response(status=200, data=None):
    r = Mock(status_code=status)
    r.json.return_value = {"items": []} if data is None else data
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError("SECRET")
    return r


def test_transient_timeout_recovers(monkeypatch):
    fetch = Mock(side_effect=[requests.Timeout("SECRET"), response()])
    monkeypatch.setattr(requests, "get", fetch)
    assert naver_news._search_naver_news("test") == {"items": []}
    assert fetch.call_count == 2


def test_toolnode_survives_naver_outage(monkeypatch):
    set_config(get_korea_config())
    fetch = Mock(side_effect=requests.Timeout("SECRET"))
    monkeypatch.setattr(requests, "get", fetch)
    builder = StateGraph(ToolState)
    builder.add_node("tools", ToolNode([get_global_news]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    result = builder.compile().invoke({"trade_date": "2026-09-25", "messages": [AIMessage(
        content="", tool_calls=[{"name": "get_global_news", "args": {"curr_date": "2026-09-25"},
                                  "id": "outage", "type": "tool_call"}])]})
    text = result["messages"][0].content
    assert "DATA_UNAVAILABLE" in text and "Timeout" in text
    assert "SECRET" not in text
    assert fetch.call_count == 3


@pytest.mark.parametrize("status", [401, 403, 400])
def test_permanent_http_error_is_not_retried(monkeypatch, status):
    fetch = Mock(return_value=response(status))
    monkeypatch.setattr(requests, "get", fetch)
    with pytest.raises(RuntimeError, match=str(status)) as caught:
        naver_news._search_naver_news("test")
    assert fetch.call_count == 1
    assert "SECRET" not in str(caught.value)


def test_invalid_success_body_is_not_empty_news(monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(return_value=response(data={"error": "SECRET"})))
    with pytest.raises(RuntimeError, match="invalid response"):
        naver_news._search_naver_news("test")


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_http_transient_retries_are_bounded(monkeypatch, status):
    fetch = Mock(return_value=response(status))
    monkeypatch.setattr(requests, "get", fetch)
    error = VendorRateLimitError if status == 429 else VendorUnavailableError
    with pytest.raises(error, match=str(status)):
        naver_news._search_naver_news("test")
    assert fetch.call_count == 3


def test_all_korean_news_sources_down_is_explicit(monkeypatch):
    set_config(get_korea_config())
    fetch = Mock(side_effect=VendorUnavailableError("network unavailable"))
    monkeypatch.setattr(naver_news, "get_news_naver", fetch)
    monkeypatch.setattr(korean_news.dart_api, "get_dart_events", fetch)
    text = router.route_to_vendor("get_news", "259960.KS", "2026-09-18", "2026-09-25")
    assert "DATA_UNAVAILABLE" in text and "Korean news sources unavailable" in text


def test_programming_error_still_surfaces(monkeypatch):
    set_config(get_korea_config())
    monkeypatch.setitem(router.VENDOR_METHODS["get_global_news"], "korea",
                        Mock(side_effect=TypeError("programming error")))
    with pytest.raises(TypeError, match="programming error"):
        router.route_to_vendor("get_global_news", "2026-09-25")
