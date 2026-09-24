"""HTTP-mocked regressions for the bounded KR data port; never needs credentials."""
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
import requests

from tradingagents.dataflows import (
    dart_api,
    ecos_api,
    kis_auth,
    kis_vendor,
    korea_ticker,
    naver_news,
)
from tradingagents.dataflows.errors import VendorNotConfiguredError, VendorRateLimitError


def response(data, status=200):
    result = Mock(status_code=status)
    result.json.return_value = data
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError("https://provider/SECRET")
    return result


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def reject(*args, **kwargs):
        pytest.fail("Unexpected network access")
    monkeypatch.setattr(requests, "get", reject)
    monkeypatch.setattr(requests, "post", reject)
    monkeypatch.setattr(korea_ticker, "_ticker_cache", korea_ticker.BUILTIN_TICKERS.copy())


def test_resolver_does_not_guess_ambiguous_name_or_unknown_exchange():
    assert korea_ticker.canonical_yahoo_symbol("삼성전자") == "005930.KS"
    assert korea_ticker.canonical_yahoo_symbol("원익IPS") == "240810.KQ"
    assert korea_ticker.canonical_yahoo_symbol("123456.KQ") == "123456.KQ"
    assert korea_ticker.get_stock_code("123456") == "123456"
    assert korea_ticker.get_stock_code("005930.KS") == "005930"
    with pytest.raises(ValueError, match="Ambiguous"):
        korea_ticker.resolve_ticker("삼성")
    with pytest.raises(ValueError, match="exchange"):
        korea_ticker.canonical_yahoo_symbol("123456")
    assert korea_ticker.resolve_ticker("") is None


def test_auth_reuses_token_and_never_exposes_secrets(monkeypatch):
    post = Mock(return_value=response({"access_token": "SECRET", "access_token_token_expired":
        (datetime.now(kis_auth.KST) + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")}))
    monkeypatch.setattr(requests, "post", post)
    auth = kis_auth.KISAuthManager("key", "secret")
    assert auth.get_token() == auth.get_token() == "SECRET"
    assert post.call_count == 1
    assert "SECRET" not in repr(auth._token)
    post.return_value = response({}, 401)
    with pytest.raises(kis_auth.KISAuthError) as caught:
        auth.get_token(force_refresh=True)
    assert "SECRET" not in str(caught.value)


def test_kis_refreshes_once_and_business_errors_are_redacted(monkeypatch):
    auth = Mock(base_url="https://openapi.koreainvestment.com:9443")
    monkeypatch.setattr(kis_vendor, "get_kis_auth_manager", lambda: auth)
    get = Mock(side_effect=[response({}, 401), response({"rt_cd": "0", "output": []})])
    monkeypatch.setattr(requests, "get", get)
    assert kis_vendor._request("/data", "test")["rt_cd"] == "0"
    assert get.call_count == 2
    assert auth.build_headers.call_args.kwargs["force_refresh"] is True
    get.side_effect = None
    get.return_value = response({"rt_cd": "1", "msg1": "SECRET"})
    with pytest.raises(kis_vendor.KISVendorError) as caught:
        kis_vendor._request("/data", "test")
    assert "SECRET" not in str(caught.value)


def bar(day, close="100"):
    return {"stck_bsop_date": day, "stck_oprc": "90", "stck_hgpr": "110",
            "stck_lwpr": "80", "stck_clpr": close, "acml_vol": "1000"}


def test_kis_paginates_and_filters_future_dates(monkeypatch):
    auth = Mock(base_url="https://openapi.koreainvestment.com:9443")
    monkeypatch.setattr(kis_vendor, "get_kis_auth_manager", lambda: auth)
    get = Mock(side_effect=[response({"rt_cd": "0", "output2": [bar("20260105"), bar("20260103"), bar("20260102")]}),
                           response({"rt_cd": "0", "output2": [bar("20260101"), bar("20251231")]})])
    monkeypatch.setattr(requests, "get", get)
    data = kis_vendor.get_kis_ohlcv_dataframe("삼성전자", "2026-01-01", "2026-01-03")
    assert list(data.Date) == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert get.call_count == 2
    assert get.call_args.kwargs["params"]["FID_INPUT_DATE_2"] == "20260101"
    assert get.call_args.kwargs["params"]["FID_ORG_ADJ_PRC"] == "1"


def test_kis_historical_fundamentals_fail_before_network():
    assert kis_vendor.get_kis_fundamentals("005930", "2020-01-01").startswith("DATA_UNAVAILABLE")


def test_indicator_200_sma_receives_sufficient_history_and_cutoff(monkeypatch):
    import pandas as pd
    days = pd.date_range("2025-01-01", periods=240)
    frame = pd.DataFrame({"Date": days.strftime("%Y-%m-%d"), "Open": 100., "High": 110.,
                          "Low": 90., "Close": range(100, 340), "Volume": 1000.})
    fetch = Mock(return_value=frame)
    monkeypatch.setattr(kis_vendor, "get_kis_ohlcv_dataframe", fetch)
    text = kis_vendor.get_kis_indicators("005930", "close_200_sma", "2025-08-28", 5)
    assert "2025-08-28" in text
    assert "2025-01-01" not in text
    assert fetch.call_args.args[-1] == "2025-08-28"


def test_dart_real_pagination_and_receipt_date_filter(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "SECRET")
    def item(day, name):
        return {"rcept_dt": day, "rcept_no": day + "000001", "report_nm": name}
    get = Mock(side_effect=[response({"status": "000", "total_page": 2, "list": [item("20260102", "SAFE1"), item("20260104", "FUTURE")]}),
                           response({"status": "000", "total_page": 2, "list": [item("20260101", "SAFE2")]})])
    monkeypatch.setattr(requests, "get", get)
    text = dart_api.get_dart_events("삼성전자", "2026-01-01", "2026-01-03")
    assert "SAFE1" in text and "SAFE2" in text and "FUTURE" not in text
    assert get.call_args.kwargs["params"]["page_no"] == "2"
    assert get.call_args.kwargs["params"]["corp_code"] == "00126380"


def test_dart_financials_exclude_later_amendments_and_missing_receipts(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "SECRET")
    get = Mock(return_value=response({"status": "000", "list": [
        {"rcept_no": "20250501000001", "account_nm": "SAFE", "thstrm_amount": "100", "sj_div": "BS"},
        {"rcept_no": "20260501000001", "account_nm": "FUTURE", "thstrm_amount": "999", "sj_div": "BS"},
        {"account_nm": "UNKNOWN", "thstrm_amount": "999", "sj_div": "BS"}]}))
    monkeypatch.setattr(requests, "get", get)
    text = dart_api.get_dart_financial_statements("005930", "2025", curr_date="2025-06-01")
    assert "SAFE" in text and "FUTURE" not in text and "UNKNOWN" not in text
    assert get.call_args.kwargs["params"]["fs_div"] == "CFS"


def test_dart_uses_standalone_only_when_consolidated_absent(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "SECRET")
    get = Mock(side_effect=[response({"status": "013"}), response({"status": "000", "list": [
        {"rcept_no": "20250301000001", "account_nm": "OFS", "sj_div": "CF", "thstrm_amount": "1"}]})])
    monkeypatch.setattr(requests, "get", get)
    text = dart_api.get_dart_financial_statements("005930", "2024", "11011", "2025-06-01")
    assert "OFS" in text
    assert get.call_args.kwargs["params"]["fs_div"] == "OFS"


def test_dart_error_does_not_echo_key(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "SECRET")
    monkeypatch.setattr(requests, "get", Mock(return_value=response({}, 403)))
    with pytest.raises(RuntimeError) as caught:
        dart_api._dart_request("list", {})
    assert "SECRET" not in str(caught.value)


def test_ecos_historical_vintage_fails_closed():
    assert "DATA_UNAVAILABLE" in ecos_api.get_macro_data("cpi", "2020-01-01")
    assert ecos_api._period("2025-04-25", "Q") == "2025Q2"


def test_ecos_paginates_filters_future_period_and_redacts_url(monkeypatch):
    monkeypatch.setenv("ECOS_API_KEY", "SECRET")
    today = datetime.now(kis_auth.KST).date()
    earlier = today - timedelta(days=1)
    future = today + timedelta(days=1)
    def row(day, value):
        return {"TIME": day.strftime("%Y%m%d"), "DATA_VALUE": value}
    get = Mock(side_effect=[response({"StatisticSearch": {"list_total_count": 3, "row": [row(earlier, "SAFE1"), row(future, "FUTURE")]}}),
                           response({"StatisticSearch": {"list_total_count": 3, "row": [row(today, "SAFE2")]}})])
    monkeypatch.setattr(requests, "get", get)
    text = ecos_api.get_ecos_stat("731Y003", "0000001", "D", str(earlier), str(today))
    assert "SAFE1" in text and "SAFE2" in text and "FUTURE" not in text
    assert "/3/1002/" in get.call_args.args[0]
    get.side_effect = requests.ConnectionError("https://ecos/SECRET/")
    with pytest.raises(RuntimeError) as caught:
        ecos_api._ecos_request("StatisticSearch", "test", "D", str(today), str(today))
    assert "SECRET" not in str(caught.value)


def test_naver_paginates_filters_publication_dates_and_uses_company_name(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")
    def item(stamp, title):
        return {"pubDate": stamp, "title": title, "link": title}
    get = Mock(side_effect=[response({"total": 200, "items": [item("Sun, 04 Jan 2026 01:00:00 +0900", "FUTURE")]}),
                           response({"total": 101, "items": [item("Fri, 02 Jan 2026 15:01:00 +0000", "SAFE"), item("invalid", "UNKNOWN")]})])
    monkeypatch.setattr(requests, "get", get)
    text = naver_news.get_news_naver("005930", "2026-01-03", "2026-01-03")
    assert "SAFE" in text and "FUTURE" not in text and "UNKNOWN" not in text
    assert get.call_args.kwargs["params"]["start"] == 101
    assert "삼성전자" in get.call_args.kwargs["params"]["query"]


def test_missing_credentials_and_rate_limit_are_typed(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    with pytest.raises(VendorNotConfiguredError):
        naver_news._search_naver_news("test")
    monkeypatch.setenv("DART_API_KEY", "key")
    monkeypatch.setattr(requests, "get", Mock(return_value=response({"status": "020"})))
    with pytest.raises(VendorRateLimitError):
        dart_api._dart_request("list", {})


def test_naver_global_none_arguments_use_config(monkeypatch):
    monkeypatch.setattr(naver_news, "get_config", lambda: {"global_news_lookback_days": 4, "global_news_article_limit": 3})
    search = Mock(return_value=([], False))
    monkeypatch.setattr(naver_news, "_dated_items", search)
    naver_news.get_global_news_naver("2026-01-10", None, None)
    assert search.call_args.args[1:] == ("2026-01-06", "2026-01-10", 3)


def test_instrument_profile_includes_explicit_market():
    assert korea_ticker.get_instrument_profile("원익IPS")["market"] == "KQ"
    assert korea_ticker.get_instrument_profile("123456.KS")["market"] == "KS"
    assert korea_ticker.get_instrument_profile("123456")["market"] is None


def test_kis_stale_prices_fail_closed(monkeypatch):
    from tradingagents.dataflows.errors import NoMarketDataError
    request = Mock(side_effect=[{"output2": [bar("20260101")]}, {"output2": []}])
    monkeypatch.setattr(kis_vendor, "_request", request)
    with pytest.raises(NoMarketDataError, match="stale"):
        kis_vendor.get_kis_stock_data("005930", "2025-12-31", "2026-02-01")


def test_kis_invalid_ohlcv_rows_are_excluded(monkeypatch):
    invalid_volume = bar("20260102")
    invalid_volume["acml_vol"] = "-1"
    request = Mock(return_value={"output2": [bar("20260101"), invalid_volume, bar("20260103", "999"), bar("20260104", "inf")]})
    monkeypatch.setattr(kis_vendor, "_request", request)
    frame = kis_vendor.get_kis_ohlcv_dataframe("005930", "2026-01-01", "2026-01-04")
    assert list(frame.Date) == ["2026-01-01"]


def test_naver_uses_cloud_hub_endpoint_and_credentials(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "test-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "test-secret")
    get = Mock(return_value=response({"items": []}))
    monkeypatch.setattr(requests, "get", get)
    assert naver_news._search_naver_news("삼성전자", display=2) == {"items": []}
    get.assert_called_once_with(
        "https://naverapihub.apigw.ntruss.com/search/v1/news",
        headers={"X-NCP-APIGW-API-KEY-ID": "test-id", "X-NCP-APIGW-API-KEY": "test-secret"},
        params={"query": "삼성전자", "display": 2, "start": 1, "sort": "date", "format": "json"},
        timeout=20,
    )


@pytest.mark.parametrize("status", [401, 429])
def test_naver_cloud_errors_do_not_expose_credentials(monkeypatch, status):
    monkeypatch.setenv("NAVER_CLIENT_ID", "test-id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "SECRET")
    monkeypatch.setattr(requests, "get", Mock(return_value=response({}, status)))
    expected = VendorRateLimitError if status == 429 else RuntimeError
    with pytest.raises(expected) as caught:
        naver_news._search_naver_news("test")
    assert "SECRET" not in str(caught.value)
