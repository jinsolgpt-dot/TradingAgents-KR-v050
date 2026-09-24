# Adapted from TradingAgents-KR ce0aa456419800c29325516f984fc55a9a8f14dd (Apache-2.0).
"""Naver news search with KST publication-date filtering and bounded pagination."""
import html
import os
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import requests

from .config import get_config
from .errors import VendorNotConfiguredError, VendorRateLimitError
from .kis_auth import KST
from .korea_ticker import get_instrument_profile

NAVER_NEWS_API_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"

def _search_naver_news(query, display=100, start=1, sort="date"):
    client_id, secret = os.getenv("NAVER_CLIENT_ID"), os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not secret:
        raise VendorNotConfiguredError("Set NAVER_CLIENT_ID and NAVER_CLIENT_SECRET")
    try:
        response = requests.get(NAVER_NEWS_API_URL,
            headers={"X-NCP-APIGW-API-KEY-ID": client_id, "X-NCP-APIGW-API-KEY": secret},
            params={"query": query, "display": display, "start": start, "sort": sort, "format": "json"}, timeout=20)
        if response.status_code == 429:
            raise VendorRateLimitError("Naver news rate limit")
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        raise RuntimeError("Naver news request failed") from None

def _clean_html(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()

def _dated_items(query, start_date, end_date, limit=100):
    first = datetime.strptime(start_date, "%Y-%m-%d").date()
    last = datetime.strptime(end_date, "%Y-%m-%d").date()
    if first > last or limit < 1:
        raise ValueError("Invalid Naver date window or limit")
    collected, seen = [], set()
    exhausted = False
    for offset in range(1, 1001, 100):
        data = _search_naver_news(query, display=100, start=offset)
        rows = data.get("items") or []
        oldest = None
        for row in rows:
            try:
                stamp = parsedate_to_datetime(row.get("pubDate", ""))
                if stamp.tzinfo is None:
                    continue
                published = stamp.astimezone(KST).date()
            except (ValueError, TypeError, OverflowError):
                continue
            oldest = min(oldest, published) if oldest else published
            key = row.get("originallink") or row.get("link") or row.get("title")
            if first <= published <= last and key not in seen:
                collected.append(row)
                seen.add(key)
        if len(collected) >= limit:
            exhausted = True
            break
        if not rows or (oldest and oldest < first) or offset + len(rows) > int(data.get("total", offset + len(rows) - 1)):
            exhausted = True
            break
    return collected[:limit], not exhausted

def _format_news_items(items):
    if not items:
        return "DATA_UNAVAILABLE: No publication-dated Naver news found in this date window."
    return "\n\n".join(f"{_clean_html(row.get('title', ''))}\nDate: {row.get('pubDate', '')}\n"
        f"{_clean_html(row.get('description', ''))}\n{row.get('originallink') or row.get('link', '')}" for row in items)

def get_news_naver(ticker, start_date, end_date):
    query = get_instrument_profile(ticker)["news_query"] + " 주식"
    items, truncated = _dated_items(query, start_date, end_date, get_config().get("news_article_limit", 20))
    note = "\nCoverage limited: Naver search's 1,000-result window was exhausted." if truncated else ""
    return f"Naver news: {ticker}, {start_date} to {end_date}. Search results are not a complete historical archive.\n" + _format_news_items(items) + note

def get_global_news_naver(curr_date, look_back_days=None, limit=None):
    config = get_config()
    look_back_days = config.get("global_news_lookback_days", 7) if look_back_days is None else look_back_days
    limit = config.get("global_news_article_limit", 10) if limit is None else limit
    if look_back_days < 0:
        raise ValueError("look_back_days must be nonnegative")
    start = (datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    items, truncated = _dated_items("한국 경제 금리 환율 증시", start, curr_date, limit)
    return f"Naver Korean macro news: {start} to {curr_date}\n" + _format_news_items(items) + ("\nCoverage limited to Naver's 1,000-result window." if truncated else "")
