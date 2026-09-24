# Adapted from TradingAgents-KR ce0aa456419800c29325516f984fc55a9a8f14dd (Apache-2.0).
"""OpenDART disclosures and filing-date-filtered financial statements.

Financial facts are accepted only when their filing receipt date is known and
no later than curr_date. Later amendments are excluded, never backfilled.
"""
import os
import re
from datetime import datetime

import requests

from .dart_classifier import format_classified_disclosures
from .errors import VendorNotConfiguredError, VendorRateLimitError
from .kis_auth import KST
from .korea_ticker import get_corp_code

DART_BASE_URL = "https://opendart.fss.or.kr/api"

def _dart_request(endpoint, params):
    key = os.getenv("DART_API_KEY", "")
    if not key:
        raise VendorNotConfiguredError("Set DART_API_KEY")
    try:
        response = requests.get(f"{DART_BASE_URL}/{endpoint}.json", params={**params, "crtfc_key": key}, timeout=20)
        if response.status_code == 429:
            raise VendorRateLimitError("DART rate limit")
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        raise RuntimeError("DART request failed") from None
    if data.get("status") == "013":
        return {"status": "013", "list": [], "total_page": 0}
    if data.get("status") == "020":
        raise VendorRateLimitError("DART daily request limit")
    if data.get("status") != "000":
        raise RuntimeError("DART rejected the request; check credentials and parameters")
    return data

def _corp_code(ticker):
    if re.fullmatch(r"\d{8}", ticker):
        return ticker
    code = get_corp_code(ticker)
    if not code:
        raise VendorNotConfiguredError("DART corporation code unavailable; update the DART ticker mapping")
    return code

def _date(value):
    return datetime.strptime(value.replace("-", ""), "%Y%m%d").date()

def _disclosures(corp_code, start_date, end_date, page_count=100):
    start, end = _date(start_date), _date(end_date)
    if start > end:
        raise ValueError("start_date must not follow end_date")
    if not 1 <= page_count <= 100:
        raise ValueError("DART page_count must be between 1 and 100")
    page, items, seen = 1, [], set()
    while True:
        data = _dart_request("list", {"corp_code": corp_code, "bgn_de": start.strftime("%Y%m%d"),
            "end_de": end.strftime("%Y%m%d"), "page_count": str(page_count), "page_no": str(page),
            "sort": "date", "sort_mth": "desc"})
        rows = data.get("list") or []
        for row in rows:
            try:
                published = _date(row.get("rcept_dt", ""))
            except ValueError:
                continue
            receipt = row.get("rcept_no")
            if start <= published <= end and receipt and receipt not in seen:
                items.append(row)
                seen.add(receipt)
        if page >= int(data.get("total_page", 1)):
            break
        if not rows:
            raise RuntimeError("DART pagination ended before the advertised final page")
        page += 1
    return items

def get_dart_disclosures(corp_code, start_date, end_date, page_count=100):
    items = _disclosures(_corp_code(corp_code), start_date, end_date, page_count)
    return f"DART disclosures: {start_date} to {end_date}\n" + format_classified_disclosures(items)

def get_dart_events(ticker, start_date, end_date):
    return get_dart_disclosures(ticker, start_date, end_date)

def _financial_rows(corp_code, year, report_code, curr_date):
    cutoff = _date(curr_date)
    for division in ("CFS", "OFS"):
        data = _dart_request("fnlttSinglAcntAll", {"corp_code": corp_code, "bsns_year": str(year),
            "reprt_code": report_code, "fs_div": division})
        rows = data.get("list") or []
        if not rows:
            continue
        safe = []
        for row in rows:
            receipt = str(row.get("rcept_no", ""))
            if not re.fullmatch(r"\d{14}", receipt):
                continue
            try:
                published = _date(receipt[:8])
            except ValueError:
                continue
            if published <= cutoff:
                safe.append(row)
        # Do not switch to standalone because consolidated data is too recent.
        return safe, division
    return [], ""

def _format_financials(rows, corp_code, year, report_code, division, curr_date, statement=None):
    if statement:
        kinds = {"IS", "CIS"} if statement == "IS" else {statement}
        rows = [row for row in rows if row.get("sj_div") in kinds]
    if not rows:
        return "DATA_UNAVAILABLE: No DART financial statements with verified filing dates on or before " + curr_date
    lines = [f"DART {division} financials: {corp_code}, {year}/{report_code}, as of {curr_date}",
             "Amounts are reported in each row's currency; quarterly reports may contain cumulative cash flows."]
    for row in rows:
        lines.append(f"[{row.get('sj_div', '')}] {row.get('account_nm', '')}: {row.get('thstrm_amount', '')} "
                     f"{row.get('currency', 'KRW')} (prior: {row.get('frmtrm_amount', '')}; filing {row['rcept_no']}")
    return "\n".join(lines)

def get_dart_financial_statements(corp_code, year, report_code="11013", curr_date=None):
    curr_date = curr_date or datetime.now(KST).strftime("%Y-%m-%d")
    if report_code not in {"11011", "11012", "11013", "11014"}:
        raise ValueError("Unknown DART report code")
    corp_code = _corp_code(corp_code)
    rows, division = _financial_rows(corp_code, year, report_code, curr_date)
    return _format_financials(rows, corp_code, year, report_code, division, curr_date)

def _statement(ticker, freq, curr_date, kind):
    if freq not in {"annual", "quarterly"}:
        raise ValueError("freq must be annual or quarterly")
    curr_date = curr_date or datetime.now(KST).strftime("%Y-%m-%d")
    cutoff = _date(curr_date)
    corp_code = _corp_code(ticker)
    reports = [(12, 31, "11011")] if freq == "annual" else [(12, 31, "11011"), (9, 30, "11014"), (6, 30, "11012"), (3, 31, "11013")]
    for year in range(cutoff.year, cutoff.year - 3, -1):
        for month, day, report_code in reports:
            if datetime(year, month, day).date() >= cutoff:
                continue
            rows, division = _financial_rows(corp_code, year, report_code, curr_date)
            result = _format_financials(rows, corp_code, year, report_code, division, curr_date, kind)
            if not result.startswith("DATA_UNAVAILABLE"):
                return result
    return "DATA_UNAVAILABLE: No DART statements with verified filing dates within the preceding three business years."

def get_balance_sheet(ticker, freq="quarterly", curr_date=None):
    return _statement(ticker, freq, curr_date, "BS")

def get_income_statement(ticker, freq="quarterly", curr_date=None):
    return _statement(ticker, freq, curr_date, "IS")

def get_cashflow(ticker, freq="quarterly", curr_date=None):
    return _statement(ticker, freq, curr_date, "CF")

def get_fundamentals(ticker, curr_date):
    return _statement(ticker, "quarterly", curr_date, None)
