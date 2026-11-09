"""demo: seed sample data so the whole flow can be shown in a short video without real ads.

What it creates (inside SOCKLOCK_HOME, by default the project folder):
    library/style_guide.md, library/winners/ (3 sample winners)
    samples/winning_script.md and .json   (input for `generate`)
    data/socklock.db with one seeded MOCK generation ("last week's pilot work")
    samples/meta_export.csv               (synthetic Ads Manager export: pilot + control ads)
"""
import csv
import shutil
from datetime import date, timedelta
from pathlib import Path

from . import config, generator, storage
from . import script as script_mod

DEMO_DATA = Path(__file__).parent / "demo_data"

# Synthetic ad results: (spend USD, impressions, link clicks, purchases).
# Pilot ads use variants v1..v6 of the seeded generation; control ads have no ID.
PILOT_ROWS = [
    (1400, 100000, 1700, 31),  # v1: CTR 1.70%, ROMI 151% -> winner
    (1100, 85000, 1190, 22),   # v2: CTR 1.40%, ROMI 136% -> winner
    (800, 70000, 840, 16),     # v3: ROMI 136%, but CTR 1.20% is below the control median
    (1200, 90000, 1620, 20),   # v4: CTR 1.80%, but ROMI 113%
    (950, 72000, 1080, 21),    # v5: CTR 1.50%, ROMI 150% -> winner
    (600, 50000, 550, 9),      # v6: weak on both
]
CONTROL_ROWS = [
    ("CTRL laundry-pile mod-11", 1500, 120000, 1560, 27),
    ("CTRL laundry-pile mod-12", 1300, 98000, 1176, 25),
    ("CTRL drawer-demo mod-07", 1100, 90000, 1260, 19),
    ("CTRL drawer-demo mod-08", 900, 75000, 825, 15),
    ("CTRL husband-test mod-03", 1250, 100000, 1500, 24),
    ("CTRL husband-test mod-04", 1000, 80000, 1000, 18),
]
SEEDED_MINUTES = 110  # time the designer logged for the seeded generation


def run_demo(home=config.HOME, reset=False):
    home = Path(home)
    library_dir, samples_dir = home / "library", home / "samples"
    db_path, out_dir = home / "data" / "socklock.db", home / "out"

    if db_path.exists() and not reset:
        raise ValueError("Демо-дані вже існують. Запустіть `demo --reset`, щоб видалити їх і почати з нуля.")
    if reset:
        for folder in (library_dir, samples_dir, out_dir):
            shutil.rmtree(folder, ignore_errors=True)
        db_path.unlink(missing_ok=True)

    # 1. Style library and sample inputs.
    (library_dir / "winners").mkdir(parents=True, exist_ok=True)
    samples_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DEMO_DATA / "style_guide.md", library_dir / "style_guide.md")
    for winner in sorted((DEMO_DATA / "winners").glob("*.md")):
        shutil.copyfile(winner, library_dir / "winners" / winner.name)
    shutil.copyfile(DEMO_DATA / "winning_script.md", samples_dir / "winning_script.md")
    shutil.copyfile(DEMO_DATA / "winning_script.json", samples_dir / "winning_script.json")

    # 2. A seeded MOCK generation, as if a designer used the tool last week.
    script = script_mod.load_script(samples_dir / "winning_script.md")
    seeded = generator.generate(script, n=10, backend="mock", library_dir=library_dir,
                                db_path=db_path, out_dir=out_dir,
                                context={"product": "SockLock magnetic socks", "audience": "US moms 28-45"})
    used_ids = [variant["id"] for variant in seeded["variants"][:len(PILOT_ROWS)]]
    storage.accept_variants(db_path, used_ids)  # the variants that went into ads were accepted
    storage.log_time(db_path, seeded["id"], SEEDED_MINUTES)

    # 3. Synthetic Meta Ads Manager export (no conversion value column -> ROMI uses LTV $68).
    csv_path = samples_dir / "meta_export.csv"
    write_meta_csv(csv_path, used_ids)
    return {"generation": seeded, "csv": csv_path, "library": library_dir, "samples": samples_dir}


def write_meta_csv(path, pilot_ids):
    end = date.today()
    start = end - timedelta(days=14)
    header = ["Reporting starts", "Reporting ends", "Campaign name", "Ad set name", "Ad name",
              "Amount spent (USD)", "Impressions", "Link clicks", "CTR (link click-through rate)", "Purchases"]
    rows = []
    for variant, (spend, impressions, clicks, purchases) in zip(pilot_ids, PILOT_ROWS):
        rows.append((f"UGC laundry | {variant} | US | 9x16", spend, impressions, clicks, purchases))
    for name, spend, impressions, clicks, purchases in CONTROL_ROWS:
        rows.append((f"{name} | US | 9x16", spend, impressions, clicks, purchases))
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        for name, spend, impressions, clicks, purchases in rows:
            writer.writerow([start.isoformat(), end.isoformat(), "SockLock | Prospecting | US",
                             "Broad US 25-54", name, f"{spend:.2f}", impressions, clicks,
                             f"{clicks / impressions * 100:.2f}", purchases])
