"""import-results: Meta Ads Manager CSV -> metrics per ad and per group -> winners -> library.

Pilot ad   = its name contains a variant ID (SLM-...-vN) -> made with the tool.
Control ad = no ID in the name -> made the old way.
"""
import csv
import io
import re
import statistics
from pathlib import Path

from . import config, ids, library, storage

# Normalized column name -> our field. The first alias found in the file wins,
# so "link clicks" is preferred over "clicks (all)".
COLUMN_ALIASES = {
    "ad_name": ["ad name", "ad"],
    "spend": ["amount spent", "spend", "cost"],
    "impressions": ["impressions", "impr"],
    "clicks": ["link clicks", "clicks", "outbound clicks"],
    "purchases": ["purchases", "website purchases", "purchase"],
    "value": ["purchases conversion value", "website purchases conversion value",
              "purchase conversion value", "conversion value", "purchase value"],
}
REQUIRED = ("ad_name", "spend", "impressions", "clicks", "purchases")
NUMBER_FIELDS = ("spend", "impressions", "clicks", "purchases", "value")


def normalize_header(name):
    """'Amount spent (USD)' -> 'amount spent', 'Clicks (all)' -> 'clicks', 'ad_name' -> 'ad name'."""
    name = name.replace("﻿", "").lower()
    name = re.sub(r"\(.*?\)", " ", name)  # drop "(USD)", "(all)" ...
    name = re.sub(r"[_\-.]+", " ", name)
    return " ".join(name.split())


def find_columns(headers):
    """{our field: header as written in the file}. Raises ValueError if a required column is missing."""
    normalized = {normalize_header(header): header for header in headers}
    columns = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                columns[field] = normalized[alias]
                break
    missing = [field for field in REQUIRED if field not in columns]
    if missing:
        raise ValueError(f"У CSV бракує колонок: {', '.join(missing)}. Знайдено: {', '.join(headers)}")
    return columns


def parse_number(text):
    """'$1,234.50' -> 1234.5; empty or '-' -> 0. Assumes a US export (dot = decimal point)."""
    text = re.sub(r"[^0-9.\-]", "", text or "")
    if text in ("", "-", "."):
        return 0.0
    return float(text)


def read_meta_csv(path, ltv=config.LTV_USD):
    """Returns (ads, value_estimated). Rows with the same ad name are summed
    (exports split by day or placement repeat an ad)."""
    text = Path(path).read_text(encoding="utf-8-sig")
    header_line = text.splitlines()[0] if text.strip() else ""
    delimiter = max([",", ";", "\t"], key=header_line.count)  # Excel in some locales uses ';'
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    columns = find_columns(reader.fieldnames or [])

    ads = {}
    for row in reader:
        name = (row.get(columns["ad_name"]) or "").strip()
        if not name:  # summary rows have no ad name
            continue
        if name not in ads:
            variant = ids.find_variant_id(name)
            ads[name] = {"ad_name": name, "variant_id": variant,
                         "group": "pilot" if variant else "control",
                         "spend": 0.0, "impressions": 0.0, "clicks": 0.0, "purchases": 0.0, "value": 0.0}
        ad = ads[name]
        for field in ("spend", "impressions", "clicks", "purchases"):
            ad[field] += parse_number(row.get(columns[field]))
        if "value" in columns:
            ad["value"] += parse_number(row.get(columns["value"]))

    value_estimated = "value" not in columns
    if value_estimated:  # no revenue column -> estimate it with the subscription LTV
        for ad in ads.values():
            ad["value"] = ad["purchases"] * ltv
    return list(ads.values()), value_estimated


def safe_div(a, b):
    return a / b if b else None


def add_metrics(row):
    """CTR, CR, CPA, ROMI for one ad or for a group total."""
    row["ctr"] = safe_div(row["clicks"], row["impressions"])   # clicks / impressions
    row["cr"] = safe_div(row["purchases"], row["clicks"])      # purchases / clicks
    row["cpa"] = safe_div(row["spend"], row["purchases"])      # spend / purchase
    row["romi"] = safe_div(row["value"], row["spend"])         # value / spend (as in the brief)
    return row


def empty_totals():
    totals = {"ads": 0}
    for field in NUMBER_FIELDS:
        totals[field] = 0.0
    return totals


def group_totals(ads):
    """Sum the numbers per group, then compute the metrics on the sums (spend-weighted)."""
    totals = {"pilot": empty_totals(), "control": empty_totals()}
    for ad in ads:
        group = totals["pilot" if ad["variant_id"] else "control"]
        group["ads"] += 1
        for field in NUMBER_FIELDS:
            group[field] += ad[field]
    for group in totals.values():
        add_metrics(group)
    return totals


def control_median_ctr(ads):
    ctrs = [ad["ctr"] for ad in ads if not ad["variant_id"] and ad["ctr"] is not None]
    return statistics.median(ctrs) if ctrs else None


def pick_winners(ads, min_romi=config.MIN_ROMI, min_ctr_ratio=1.0, min_spend=0.0):
    """Winner = pilot ad with ROMI >= min_romi AND CTR >= min_ctr_ratio x control median CTR
    (AND spend >= min_spend, off by default). Sets ad["winner"]. Returns (winners, control median)."""
    median = control_median_ctr(ads)
    winners = []
    for ad in ads:
        if not ad["variant_id"]:
            ad["winner"] = False
            continue
        romi_ok = ad["romi"] is not None and ad["romi"] >= min_romi
        # With no control ads we cannot compare CTR, so only ROMI decides.
        ctr_ok = median is None or (ad["ctr"] is not None and ad["ctr"] >= median * min_ctr_ratio)
        spend_ok = ad["spend"] >= min_spend
        ad["winner"] = romi_ok and ctr_ok and spend_ok
        if ad["winner"]:
            winners.append(ad)
    return winners, median


def import_results(csv_path, db_path=config.DB_PATH, library_dir=config.LIBRARY_DIR,
                   min_romi=config.MIN_ROMI, min_ctr_ratio=1.0, min_spend=0.0, ltv=config.LTV_USD):
    """The whole feedback loop. Returns a summary dict for printing."""
    ads, value_estimated = read_meta_csv(csv_path, ltv)
    for ad in ads:
        add_metrics(ad)
    winners, median = pick_winners(ads, min_romi, min_ctr_ratio, min_spend)
    storage.replace_ad_results(db_path, ads, value_estimated, csv_path)

    copied, already_there, unknown = [], [], []
    for ad in winners:
        variant = storage.get_variant(db_path, ad["variant_id"])
        if variant is None:  # ID from another database or a typo in the ad name
            unknown.append(ad["variant_id"])
            continue
        note = f"CTR {ad['ctr']:.2%}, ROMI {ad['romi']:.0%}, spend ${ad['spend']:,.0f}"
        path = library.save_winner_script(library_dir, ad["variant_id"], variant["script"], note)
        if path:
            copied.append(path)
        else:
            already_there.append(ad["variant_id"])

    return {
        "ads": ads, "totals": group_totals(ads), "control_median_ctr": median,
        "winners": winners, "copied": copied, "already_there": already_there, "unknown": unknown,
        "value_estimated": value_estimated, "ltv": ltv,
    }
