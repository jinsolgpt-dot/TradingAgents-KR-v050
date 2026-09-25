"""Verify disputed cash-flow profit against the same filed DART document.

Never infer a replacement from another statement: require a unique table with
matching cash-flow totals, period headers and the exact account label.
"""
import io
import os
import re
import zipfile
from functools import lru_cache
from html.parser import HTMLParser

import requests


def number(value):
    text = str(value or "").strip().replace(",", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    return text if re.fullmatch(r"-?\d+(?:\.\d+)?", text) else None


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.stack.append({"rows": [], "row": None, "cell": None})
        elif self.stack:
            table = self.stack[-1]
            if tag == "tr":
                table["row"] = []
            elif tag in {"td", "th", "te", "tu"} and table["row"] is not None:
                table["cell"] = []

    def handle_data(self, data):
        if self.stack and self.stack[-1]["cell"] is not None:
            self.stack[-1]["cell"].append(data)

    def handle_endtag(self, tag):
        if not self.stack:
            return
        table = self.stack[-1]
        if tag in {"td", "th", "te", "tu"} and table["cell"] is not None:
            table["row"].append("".join(table["cell"]).strip())
            table["cell"] = None
        elif tag == "tr" and table["row"] is not None:
            table["rows"].append(table["row"])
            table["row"] = None
        elif tag == "table":
            self.tables.append(self.stack.pop()["rows"])


@lru_cache(maxsize=8)
def _document_tables(receipt):
    if not re.fullmatch(r"\d{14}", receipt):
        raise ValueError("Invalid DART receipt")
    try:
        response = requests.get("https://opendart.fss.or.kr/api/document.xml",
                                params={"crtfc_key": os.environ["DART_API_KEY"], "rcept_no": receipt}, timeout=30)
        response.raise_for_status()
        if len(response.content) > 25_000_000:
            raise ValueError("Oversized archive")
        tables = []
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            files = [f for f in archive.infolist() if f.filename.lower().endswith(".xml")]
            if sum(f.file_size for f in files) > 50_000_000:
                raise ValueError("Oversized document")
            for file in files:
                parser = _Tables()
                parser.feed(archive.read(file).decode("utf-8"))
                tables.extend(parser.tables)
        return tables
    except (requests.RequestException, ValueError, KeyError, zipfile.BadZipFile, OSError):
        raise RuntimeError("DART source document unavailable") from None


def verified_cashflow_profit(row, rows):
    """Return current/prior source values only if statement identity is proven."""
    totals = {"ifrs-full_CashFlowsFromUsedInOperatingActivities",
              "ifrs-full_CashFlowsFromUsedInInvestingActivities",
              "ifrs-full_CashFlowsFromUsedInFinancingActivities"}
    anchors = {number(r.get("thstrm_amount")) for r in rows
               if r.get("sj_div") == "CF" and r.get("account_id") in totals
               and r.get("rcept_no") == row.get("rcept_no")}
    anchors.discard(None)
    if len(anchors) < 2 or not row.get("thstrm_nm") or not row.get("frmtrm_q_nm"):
        return None
    try:
        tables = _document_tables(row["rcept_no"])
    except RuntimeError:
        return None
    def normalize(value):
        return re.sub(r"\s+", "", value)

    def account_label(value):
        return normalize(value).replace("(손실)", "").replace("(이익)", "")
    matches = []
    for table in tables:
        headers = [normalize(cell) for tr in table[:3] for cell in tr]
        current_header, prior_header = normalize(row["thstrm_nm"]), normalize(row["frmtrm_q_nm"])
        if current_header not in headers or prior_header not in headers:
            continue
        if headers.index(current_header) >= headers.index(prior_header):
            continue
        # Matching exact totals also checks unit and consolidated/standalone scope.
        current_values = {number(tr[1]) for tr in table if len(tr) == 3}
        if not anchors.issubset(current_values):
            continue
        for tr in table:
            if len(tr) == 3 and account_label(tr[0]) == account_label(row.get("account_nm", "")):
                current, prior = number(tr[1]), number(tr[2])
                if current is not None and prior is not None:
                    matches.append({"current": current, "prior": prior})
    return matches[0] if len(matches) == 1 else None
