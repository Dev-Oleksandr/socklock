import pytest

from socklock import results

META_CSV = (
    "﻿Reporting starts,Ad name,Amount spent (USD),Impressions,Link clicks,Clicks (all),"
    "Purchases,Purchases conversion value\n"
    '2026-11-01,UGC | SLM-20261109-K7QX-v1 | US,"1,000.00",100000,2000,3500,20,"$1,500.00"\n'
    "2026-11-01,CTRL mod-1,1000,100000,1000,2000,10,700\n"
    "2026-11-01,CTRL mod-2,500,50000,750,900,5,300\n"
    ",,3500,250000,3750,6400,35,2500\n"  # summary row without an ad name
)


def write(tmp_path, text, name="export.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_normalize_header():
    assert results.normalize_header("Amount spent (USD)") == "amount spent"
    assert results.normalize_header("Clicks (all)") == "clicks"
    assert results.normalize_header("﻿Ad_name") == "ad name"
    assert results.normalize_header("Impr.") == "impr"


def test_read_meta_csv(tmp_path):
    ads, estimated = results.read_meta_csv(write(tmp_path, META_CSV))
    assert estimated is False
    assert [ad["ad_name"] for ad in ads] == ["UGC | SLM-20261109-K7QX-v1 | US", "CTRL mod-1", "CTRL mod-2"]
    pilot = ads[0]
    assert pilot["variant_id"] == "SLM-20261109-K7QX-v1" and pilot["group"] == "pilot"
    assert pilot["spend"] == 1000.0 and pilot["value"] == 1500.0
    assert pilot["clicks"] == 2000  # "Link clicks" wins over "Clicks (all)"
    assert ads[1]["group"] == "control"


def test_column_variants_semicolon_and_no_value_column(tmp_path):
    text = ("Ad Name;Amount Spent (EUR);Impressions;Clicks (all);Website purchases\n"
            "SLM-20261109-K7QX-v2;100;10000;150;2\n"
            "SLM-20261109-K7QX-v2;50;5000;50;1\n")  # same ad twice (e.g. daily rows) -> summed
    ads, estimated = results.read_meta_csv(write(tmp_path, text), ltv=68)
    assert estimated is True
    assert len(ads) == 1
    ad = ads[0]
    assert (ad["spend"], ad["impressions"], ad["clicks"], ad["purchases"]) == (150, 15000, 200, 3)
    assert ad["value"] == 3 * 68


def test_missing_required_column(tmp_path):
    with pytest.raises(ValueError, match="clicks"):
        results.read_meta_csv(write(tmp_path, "Ad name,Amount spent (USD),Impressions,Purchases\nx,1,2,3\n"))


def test_parse_number():
    assert results.parse_number("$1,234.50") == 1234.5
    assert results.parse_number("") == 0
    assert results.parse_number("-") == 0
    assert results.parse_number("12%") == 12


def test_metric_math():
    ad = results.add_metrics({"spend": 1000, "impressions": 100000, "clicks": 2000, "purchases": 20, "value": 1500})
    assert ad["ctr"] == pytest.approx(0.02)   # 2000 / 100000
    assert ad["cr"] == pytest.approx(0.01)    # 20 / 2000
    assert ad["cpa"] == pytest.approx(50)     # 1000 / 20
    assert ad["romi"] == pytest.approx(1.5)   # 1500 / 1000
    empty = results.add_metrics({"spend": 0, "impressions": 0, "clicks": 0, "purchases": 0, "value": 0})
    assert empty["ctr"] is None and empty["cpa"] is None and empty["romi"] is None


def test_group_totals(tmp_path):
    ads, _ = results.read_meta_csv(write(tmp_path, META_CSV))
    totals = results.group_totals([results.add_metrics(ad) for ad in ads])
    assert totals["pilot"]["ads"] == 1
    assert totals["control"]["ads"] == 2
    assert totals["control"]["ctr"] == pytest.approx(1750 / 150000)  # computed on the sums
    assert totals["control"]["romi"] == pytest.approx(1000 / 1500)


def make_ad(name, variant, ctr, romi, spend=100.0):
    return {"ad_name": name, "variant_id": variant, "spend": spend, "ctr": ctr, "romi": romi}


def test_pick_winners():
    ads = [
        make_ad("c1", None, 0.010, 1.0), make_ad("c2", None, 0.012, 1.0), make_ad("c3", None, 0.014, 1.0),
        make_ad("p1", "SLM-20261109-AAAA-v1", 0.013, 1.40),   # winner
        make_ad("p2", "SLM-20261109-AAAA-v2", 0.011, 1.60),   # CTR below control median 1.2%
        make_ad("p3", "SLM-20261109-AAAA-v3", 0.020, 1.20),   # ROMI below 130%
        make_ad("p4", "SLM-20261109-AAAA-v4", 0.012, 1.30),   # exactly on both thresholds -> winner
    ]
    winners, median = results.pick_winners(ads)
    assert median == pytest.approx(0.012)
    assert [ad["ad_name"] for ad in winners] == ["p1", "p4"]
    # stricter thresholds are configurable
    winners, _ = results.pick_winners(ads, min_romi=1.35, min_ctr_ratio=1.0)
    assert [ad["ad_name"] for ad in winners] == ["p1"]
    winners, _ = results.pick_winners(ads, min_spend=500)
    assert winners == []


def test_pick_winners_without_control_uses_romi_only():
    ads = [make_ad("p1", "SLM-20261109-AAAA-v1", 0.001, 1.5)]
    winners, median = results.pick_winners(ads)
    assert median is None
    assert len(winners) == 1
