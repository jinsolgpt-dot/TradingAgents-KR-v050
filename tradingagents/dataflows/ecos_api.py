# Adapted from TradingAgents-KR ce0aa456419800c29325516f984fc55a9a8f14dd (Apache-2.0).
"""Bank of Korea ECOS statistics; historical vintages fail closed.

ECOS StatisticSearch exposes revised series without release/vintage dates.
Historical as-of analysis must not substitute these current revised values.
"""
import calendar
import os
from datetime import datetime, timedelta

import requests

from .errors import VendorNotConfiguredError, VendorRateLimitError
from .kis_auth import KST

ECOS_BASE_URL = "https://ecos.bok.or.kr/api"
MACRO_STAT_CODES = {
    "base_rate": {"stat_code": "722Y001", "item_code": "0101000", "cycle": "M", "label": "한국은행 기준금리"},
    "usd_krw": {"stat_code": "731Y003", "item_code": "0000003", "cycle": "D", "label": "원/달러 환율 (15:30 종가)"},
    "kospi": {"stat_code": "802Y001", "item_code": "0001000", "cycle": "D", "label": "KOSPI"},
    "cpi": {"stat_code": "901Y009", "item_code": "0", "cycle": "M", "label": "소비자물가지수"},
    "m2": {"stat_code": "161Y005", "item_code": "BBHS00", "cycle": "M", "label": "M2 광의통화 (평잔, 계절조정)"},
}

def _period(value, cycle):
    day = datetime.strptime(value.replace("-", ""), "%Y%m%d")
    if cycle == "D":
        return day.strftime("%Y%m%d")
    if cycle == "M":
        return day.strftime("%Y%m")
    if cycle == "Q":
        return f"{day.year}Q{(day.month - 1) // 3 + 1}"
    if cycle == "A":
        return str(day.year)
    raise ValueError("ECOS cycle must be D, M, Q or A")

def _period_end(value, cycle):
    if cycle == "D":
        return datetime.strptime(value, "%Y%m%d").date()
    year = int(value[:4])
    month = int(value[4:6]) if cycle == "M" else int(value[-1]) * 3 if cycle == "Q" else 12
    return datetime(year, month, calendar.monthrange(year, month)[1]).date()

def _ecos_request(service, stat_code, cycle, start_date, end_date, item_code="", start_count=1, end_count=1000):
    key = os.getenv("ECOS_API_KEY")
    if not key:
        raise VendorNotConfiguredError("Set ECOS_API_KEY")
    url = "/".join([ECOS_BASE_URL, service, key, "json", "kr", str(start_count), str(end_count),
        stat_code, cycle, _period(start_date, cycle), _period(end_date, cycle), item_code])
    try:
        response = requests.get(url, timeout=20)
        if response.status_code == 429:
            raise VendorRateLimitError("ECOS rate limit")
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        # Never include the exception: ECOS puts its credential in the URL.
        raise RuntimeError("ECOS request failed") from None
    result = data.get("RESULT", {})
    if result.get("CODE") == "INFO-200":
        return {service: {"row": [], "list_total_count": 0}}
    if result and result.get("CODE") != "INFO-000":
        raise RuntimeError("ECOS rejected the request")
    if service not in data:
        raise RuntimeError("ECOS returned an invalid response")
    return data

def get_ecos_stat(stat_code, item_code, cycle, start_date, end_date, count=1000):
    start = datetime.strptime(start_date.replace("-", ""), "%Y%m%d").date()
    end = datetime.strptime(end_date.replace("-", ""), "%Y%m%d").date()
    if start > end or count < 1:
        raise ValueError("Invalid ECOS date window or count")
    if end != datetime.now(KST).date():
        return "DATA_UNAVAILABLE: ECOS has no historical release vintages; revised current series cannot be used for historical as-of analysis."
    rows, offset = [], 1
    while True:
        payload = _ecos_request("StatisticSearch", stat_code, cycle, start_date, end_date, item_code, offset, offset + 999)
        result = payload["StatisticSearch"]
        page = result.get("row") or []
        for row in page:
            try:
                period_end = _period_end(str(row.get("TIME", "")), cycle)
            except (ValueError, IndexError):
                continue
            if start <= period_end <= end:
                rows.append(row)
        if offset + len(page) > int(result.get("list_total_count", 0)):
            break
        if not page:
            raise RuntimeError("ECOS pagination ended before the advertised final page")
        offset += len(page)
    if not rows:
        return "DATA_UNAVAILABLE: No ECOS observations in the requested period."
    rows = sorted({str(row["TIME"]): row for row in rows}.values(), key=lambda row: row["TIME"])[-count:]
    return (f"ECOS current vintage, retrieved {end_date}; series {stat_code}/{item_code}, cycle {cycle}. "
            "These published values are usable for analysis on the retrieval date, but not as historical vintages. "
            "Observation periods are not release dates; the latest observation need not describe today's level.\n") + "\n".join(
        f"{row['TIME']}: {row.get('DATA_VALUE', '')} {row.get('UNIT_NAME', '')}" for row in rows)

def get_macro_data(indicator, curr_date, look_back_days=None):
    if indicator not in MACRO_STAT_CODES:
        raise ValueError("ECOS indicator must be one of: " + ", ".join(MACRO_STAT_CODES))
    days = 365 if look_back_days is None else look_back_days
    if days < 0:
        raise ValueError("look_back_days must be nonnegative")
    spec = MACRO_STAT_CODES[indicator]
    start = (datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    return spec["label"] + "\n" + get_ecos_stat(spec["stat_code"], spec["item_code"], spec["cycle"], start, curr_date)

def get_korea_macro_summary(trade_date, lookback_months=3):
    return "\n\n".join(get_macro_data(key, trade_date, lookback_months * 30) for key in MACRO_STAT_CODES)
