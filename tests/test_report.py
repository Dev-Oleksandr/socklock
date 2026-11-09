import pytest

from socklock import demo, generator, report, results, storage
from socklock import script as script_mod

SCRIPT = script_mod.parse_script_text("# T\n## Scene 1\nVO: hook\n## Scene 2\nVO: two\n## Scene 3\nVO: three")


def statuses(rep):
    return {row["name"]: row["status"] for row in rep["rows"]}


def test_report_without_data(tmp_path):
    rep = report.build_report(tmp_path / "empty.db")
    assert set(statuses(rep).values()) == {"НЕМАЄ ДАНИХ"}
    assert rep["overall"] == "FAIL"


def test_report_thresholds(tmp_path):
    db = tmp_path / "t.db"
    gen = generator.generate(SCRIPT, n=4, backend="mock", db_path=db,
                             library_dir=tmp_path / "lib", out_dir=tmp_path / "out")
    ids = [v["id"] for v in gen["variants"]]
    storage.accept_variants(db, ids[:2])          # 2/4 = 50% -> PASS (>= 50%)
    storage.log_time(db, gen["id"], 100)
    storage.log_time(db, gen["id"], 150)          # average 125 min -> FAIL (> 120)
    ads = [
        {"ad_name": "a", "variant_id": ids[0], "spend": 100, "impressions": 10000, "clicks": 150, "purchases": 2, "value": 140},
        {"ad_name": "b", "variant_id": None, "spend": 100, "impressions": 10000, "clicks": 100, "purchases": 2, "value": 140},
    ]
    storage.replace_ad_results(db, ads, value_estimated=False, source_file="x.csv")

    rep = report.build_report(db)
    s = statuses(rep)
    assert s["Acceptance rate"] == "PASS"
    assert s["Хвилин на модифікацію"] == "FAIL"
    assert s["CTR: перевірка vs контроль"] == "PASS"   # 1.5% vs 1.0%
    assert s["ROMI групи перевірки"] == "PASS"            # 140 / 100 = 140%
    assert rep["overall"] == "FAIL"
    assert rep["projected_mods"] == pytest.approx(240 * 180 / 125)
    assert rep["mock_generations"] == 1
    assert "FAIL" in report.format_report(rep)


def test_accept_unknown_and_log_time_errors(tmp_path):
    db = tmp_path / "t.db"
    accepted, unknown = storage.accept_variants(db, ["SLM-20261109-ZZZZ-v1"])
    assert accepted == [] and unknown == ["SLM-20261109-ZZZZ-v1"]
    with pytest.raises(ValueError):
        storage.log_time(db, "SLM-20261109-ZZZZ", 50)


def test_demo_flow_end_to_end(tmp_path):
    """demo -> import-results -> report, all offline."""
    info = demo.run_demo(tmp_path)
    db = tmp_path / "data" / "socklock.db"
    summary = results.import_results(info["csv"], db, tmp_path / "library")
    assert summary["value_estimated"] is True                 # demo CSV has no value column -> LTV
    assert [ad["variant_id"][-2:] for ad in summary["winners"]] == ["v1", "v2", "v5"]
    assert len(summary["copied"]) == 3
    assert len(list((tmp_path / "library" / "winners").glob("*.md"))) == 6  # 3 samples + 3 winners
    # importing again does not duplicate winners
    assert results.import_results(info["csv"], db, tmp_path / "library")["copied"] == []

    rep = report.build_report(db)
    s = statuses(rep)
    assert s["Acceptance rate"] == "PASS"       # 6 of 10 seeded variants were used in ads
    assert s["Хвилин на модифікацію"] == "PASS"  # 110 min
    assert s["CTR: перевірка vs контроль"] == "PASS"
    assert s["ROMI групи перевірки"] == "PASS"
    with pytest.raises(ValueError):
        demo.run_demo(tmp_path)                 # refuses to overwrite without reset
    demo.run_demo(tmp_path, reset=True)
