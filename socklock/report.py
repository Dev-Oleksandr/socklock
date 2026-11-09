"""report: pilot metrics vs success thresholds, PASS / FAIL per metric."""
from . import config, results, storage


def check(name, value_text, target_text, passed):
    """One report row. passed=None means there is no data yet."""
    status = "НЕМАЄ ДАНИХ" if passed is None else ("PASS" if passed else "FAIL")
    return {"name": name, "value": value_text, "target": target_text, "status": status}


def pct(x):
    return "—" if x is None else f"{x:.1%}"


def build_report(db_path=config.DB_PATH):
    stats = storage.pilot_stats(db_path)
    ads = [results.add_metrics(ad) for ad in storage.load_ad_results(db_path)]
    totals = results.group_totals(ads)
    pilot, control = totals["pilot"], totals["control"]
    rows = []

    # 1. Acceptance rate: accepted variants / generated variants.
    acceptance = results.safe_div(stats["accepted"], stats["generated"])
    rows.append(check(
        "Acceptance rate", f"{pct(acceptance)} ({stats['accepted']}/{stats['generated']})",
        f">= {config.MIN_ACCEPTANCE:.0%}",
        None if acceptance is None else acceptance >= config.MIN_ACCEPTANCE))

    # 2. Average minutes per modification.
    minutes = stats["minutes"]
    avg_minutes = sum(minutes) / len(minutes) if minutes else None
    rows.append(check(
        "Хвилин на модифікацію", "—" if avg_minutes is None else f"{avg_minutes:.0f} хв (n={len(minutes)})",
        f"<= {config.MAX_MINUTES_PER_MOD} хв",
        None if avg_minutes is None else avg_minutes <= config.MAX_MINUTES_PER_MOD))

    # 3. CTR of tool variants vs control (group totals).
    have_ctr = pilot["ctr"] is not None and control["ctr"] is not None
    rows.append(check(
        "CTR: перевірка vs контроль", f"{pct(pilot['ctr'])} vs {pct(control['ctr'])}", "не нижче контролю",
        pilot["ctr"] >= control["ctr"] if have_ctr else None))

    # 4. ROMI of tool variants.
    rows.append(check(
        "ROMI групи перевірки", f"{pct(pilot['romi'])}", f">= {config.MIN_ROMI:.0%}",
        None if pilot["romi"] is None else pilot["romi"] >= config.MIN_ROMI))

    # Business view: if the whole team worked at the measured speed with the same hours.
    projected = None
    if avg_minutes:
        projected = config.BASELINE_MODS_PER_MONTH * config.BASELINE_MINUTES_PER_MOD / avg_minutes

    return {
        "rows": rows,
        "overall": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
        "projected_mods": projected,
        "per_model": stats["per_model"],
        "mock_generations": stats["mock_generations"],
        "value_estimated": any(ad["value_estimated"] for ad in ads),
        "pilot": pilot, "control": control,
    }


def format_report(report):
    lines = ["SockLock Hooks — звіт перевірки гіпотези", ""]
    lines.append(f"{'Метрика':<28} {'Значення':<24} {'Поріг':<20} Статус")
    lines.append("-" * 84)
    for row in report["rows"]:
        lines.append(f"{row['name']:<28} {row['value']:<24} {row['target']:<20} {row['status']}")
    lines.append("-" * 84)
    lines.append(f"Загальний вердикт: {report['overall']}")
    lines.append("")
    if report["projected_mods"]:
        lines.append(
            f"Прогноз потужності: {config.BASELINE_MODS_PER_MONTH} x {config.BASELINE_MINUTES_PER_MOD} хв / "
            f"виміряний час = {report['projected_mods']:.0f} модифікацій/міс (ціль {config.TARGET_MODS_PER_MONTH})")
    if report["per_model"]:
        lines.append("Acceptance за моделями (для A/B Sonnet vs Opus):")
        for row in report["per_model"]:
            rate = results.safe_div(row["accepted"], row["generated"])
            lines.append(f"  {row['model']:<22} {pct(rate)} ({row['accepted']}/{row['generated']})")
    if report["value_estimated"]:
        lines.append(f"ROMI розраховано як purchases x LTV ${config.LTV_USD:.0f} (у CSV не було колонки цінності конверсій).")
    if report["mock_generations"]:
        lines.append(f"Увага: mock-генерацій (демо) у базі: {report['mock_generations']}. "
                     "Для справжньої перевірки гіпотези почніть з чистої бази.")
    return "\n".join(lines)
