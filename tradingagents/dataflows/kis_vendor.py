# Adapted from TradingAgents-KR ce0aa456419800c29325516f984fc55a9a8f14dd (Apache-2.0).
"""Read-only Korean stock data. Daily bars are raw (unadjusted) KRW prices."""
from datetime import datetime, timedelta

import pandas as pd
import requests
from stockstats import wrap

from .errors import NoMarketDataError, VendorRateLimitError
from .kis_auth import KST, get_kis_auth_manager
from .korea_ticker import get_stock_code
from .vendors.yahoo.ohlcv import _assert_ohlcv_not_stale


class KISVendorError(RuntimeError):
    pass

def _request(path, tr_id, params=None):
    auth = get_kis_auth_manager()
    try:
        for refresh in (False, True):
            response = requests.get(auth.base_url + path,
                headers=auth.build_headers(tr_id=tr_id, force_refresh=refresh),
                params=params or {}, timeout=20)
            if response.status_code != 401 or refresh:
                break
        if response.status_code == 429:
            raise VendorRateLimitError("KIS rate limit")
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        raise KISVendorError("KIS market-data request failed") from None
    if data.get("rt_cd") not in ("0", 0):
        if data.get("msg_cd") == "EGW00201":
            raise VendorRateLimitError("KIS rate limit")
        raise KISVendorError("KIS rejected the market-data request")
    return data

def _normalize_kis_symbol(symbol):
    code = get_stock_code(symbol)
    if not code:
        raise ValueError("KIS requires an unambiguous Korean company name or six-digit code")
    return code

def get_kis_ohlcv_dataframe(symbol, start_date, end_date):
    code = _normalize_kis_symbol(symbol)
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    if start > end:
        raise ValueError("start_date must not follow end_date")
    cursor, rows = end, []
    while cursor >= start:
        payload = _request("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            "FHKST03010100", {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": start.strftime("%Y%m%d"), "FID_INPUT_DATE_2": cursor.strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "1"})
        page = payload.get("output2") or []
        if not page:
            break
        dates = pd.to_datetime([r.get("stck_bsop_date") for r in page], format="%Y%m%d", errors="coerce")
        eligible = [d for d in dates if pd.notna(d) and d <= cursor]
        if not eligible:
            raise KISVendorError("KIS pagination returned no valid dates in the requested window")
        rows.extend(page)
        earliest = min(eligible)
        cursor = earliest.to_pydatetime() - timedelta(days=1)
    columns = {"stck_bsop_date": "Date", "stck_oprc": "Open", "stck_hgpr": "High",
               "stck_lwpr": "Low", "stck_clpr": "Close", "acml_vol": "Volume"}
    df = pd.DataFrame(rows).reindex(columns=list(columns)).rename(columns=columns)
    df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d", errors="coerce")
    for column in list(columns.values())[1:]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.replace([float("inf"), float("-inf")], float("nan")).dropna()
    valid = (df["Date"].between(start, end) & (df["Low"] > 0) & (df["Volume"] >= 0)
             & (df["Low"] <= df["Open"]) & (df["Low"] <= df["Close"])
             & (df["High"] >= df["Open"]) & (df["High"] >= df["Close"]))
    df = df.loc[valid]
    df = df.drop_duplicates("Date").sort_values("Date").reset_index(drop=True)
    _assert_ohlcv_not_stale(df, end_date, symbol, code)
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    return df

def get_kis_stock_data(symbol, start_date, end_date):
    df = get_kis_ohlcv_dataframe(symbol, start_date, end_date)
    if df.empty:
        raise NoMarketDataError(symbol, detail="KIS returned no daily bars in the requested window")
    return f"KIS daily OHLCV for {symbol}; raw/unadjusted KRW prices (corporate actions may cause discontinuities).\n" + df.to_csv(index=False)

def get_kis_indicators(symbol, indicator, curr_date, look_back_days=30):
    supported = {"close_50_sma", "close_200_sma", "close_10_ema", "macd", "macdh", "macds", "rsi", "boll", "boll_ub", "boll_lb", "atr", "vwma", "mfi"}
    if indicator not in supported:
        raise ValueError("Unsupported KIS indicator")
    if look_back_days < 0:
        raise ValueError("look_back_days must be nonnegative")
    end = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days + 730)
    df = get_kis_ohlcv_dataframe(symbol, start.strftime("%Y-%m-%d"), curr_date)
    if df.empty:
        raise NoMarketDataError(symbol)
    stock = wrap(df.rename(columns=str.lower).set_index("date"))
    values = stock[indicator]
    # stockstats emits short-history averages; suppress those until their period is available.
    warmup = {"close_200_sma": 200, "close_50_sma": 50, "close_10_ema": 10,
              "macd": 35, "macdh": 35, "macds": 35, "rsi": 14,
              "boll": 20, "boll_ub": 20, "boll_lb": 20, "atr": 14, "vwma": 14, "mfi": 14}[indicator]
    values = values.copy()
    values.iloc[:warmup - 1] = float("nan")
    report = values.loc[values.index >= (end - timedelta(days=look_back_days)).strftime("%Y-%m-%d")].dropna()
    if report.empty:
        raise NoMarketDataError(symbol, detail="Insufficient KIS indicator history")
    return f"KIS {indicator}; raw/unadjusted prices\n" + report.to_csv()

def get_kis_fundamentals(ticker, curr_date):
    asof = datetime.strptime(curr_date, "%Y-%m-%d").date()
    if asof != datetime.now(KST).date():
        return "DATA_UNAVAILABLE: KIS fundamentals are current snapshots; historical point-in-time fundamentals are unavailable. Use DART filing-dated statements."
    symbol = _normalize_kis_symbol(ticker)
    sections = []
    for path, tr_id, params in [
        ("/uapi/domestic-stock/v1/quotations/search-stock-info", "CTPF1002R", {"PRDT_TYPE_CD": "300", "PDNO": symbol}),
        ("/uapi/domestic-stock/v1/finance/financial-ratio", "FHKST66430300", {"FID_DIV_CLS_CODE": "1", "fid_cond_mrkt_div_code": "J", "fid_input_iscd": symbol})]:
        data = _request(path, tr_id, params).get("output") or []
        sections.append(pd.DataFrame([data] if isinstance(data, dict) else data).to_csv(index=False))
    return "KIS current company information and financial ratios; retrieved " + curr_date + "\n" + "\n".join(sections)
