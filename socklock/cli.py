"""Command line: python -m socklock <command>. Only argument parsing and printing live here;
the real work is done in generator / library / storage / results / report / web / demo."""
import argparse
import sys

from . import config, demo, generator, library, report, results, storage, web
from . import script as script_mod
from .backends import BACKENDS, GenerationError
from .script import ELEMENTS

GROUP_LABELS = {"pilot": "перевірка", "control": "контроль"}      # table column
GROUP_TITLES = {"pilot": "Група перевірки", "control": "Контрольна група"}
MOCK_BANNER = "*** MOCK-РЕЖИМ: офлайн-заглушка для тестів і демо. Тексти НЕ від Claude. ***"


def pct(x):
    return "—" if x is None else f"{x:.2%}"


def money(x):
    return "—" if x is None else f"${x:,.2f}"


# ---------------------------------------------------------------- commands

def generate_options(args, settings):
    """Explicit CLI flags win over the file's front matter; the front matter wins over defaults."""
    def pick(flag, key, default):
        if flag is not None:
            return flag
        return settings.get(key, default)

    return {
        "elements": pick(args.elements, "elements", list(ELEMENTS)),
        "n": pick(args.n, "variants", config.DEFAULT_VARIANTS),
        "model": pick(args.model, "model", config.DEFAULT_MODEL),
        "context": {"context": pick(args.context, "context", ""),
                    "product": args.product, "audience": args.audience, "angle": args.angle},
    }


def cmd_generate(args):
    script, settings = script_mod.load_document(args.script)
    options = generate_options(args, settings)
    backend = config.resolve_backend(args.backend, args.mock)
    if settings:
        print("Налаштування з файлу: " + ", ".join(f"{key}={value}" for key, value in settings.items()))
    if args.show_prompt:  # print exactly what the model would get, without calling it
        print("===== SYSTEM (стабільний префікс, кешується) =====")
        print(generator.build_system_prompt(config.LIBRARY_DIR))
        print("\n===== USER (змінна частина) =====")
        clean_context = {k: v for k, v in options["context"].items() if v}
        elements = [e for e in ELEMENTS if e in options["elements"]]
        print(generator.build_user_message(script, elements, options["n"], clean_context))
        return 0
    if backend != "mock":
        print(f"Генерую варіанти (n={options['n']}) через {backend} ({options['model']})... "
              "це може тривати хвилину.", flush=True)
    generation = generator.generate(script, options["elements"], options["n"], options["context"],
                                    backend=backend, model=options["model"], effort=args.effort)
    print_generation(generation)
    return 0


def print_generation(generation):
    g = generation
    if g["backend"] == "mock":
        print(MOCK_BANNER)
    line = f"Генерація {g['id']} · backend: {g['backend']} · модель: {g['model']}"
    if g["served_model"] and g["served_model"] not in (g["model"], "mock"):
        line += f" (відповіла: {g['served_model']})"
    print(line)
    usage = g["usage"] or {}
    if usage:
        print(f"Токени: вхід {usage.get('input_tokens', 0)}, вихід {usage.get('output_tokens', 0)}, "
              f"кеш прочитано {usage.get('cache_read_input_tokens', 0)}, "
              f"кеш записано {usage.get('cache_creation_input_tokens', 0)}")
    if len(g["variants"]) < g["requested"]:
        print(f"Увага: модель повернула {len(g['variants'])} з {g['requested']} варіантів.")
    for variant in g["variants"]:
        changed = generator.changed_texts(g, variant)
        print(f"\n{variant['id']}  [{variant['angle']}]")
        if "hook" in changed:
            print(f"  Хук:          {changed['hook']}")
        for number, text in enumerate(changed.get("first_lines", []), start=2):
            print(f"  Сцена {number} VO:   {text}")
        if "onscreen_text" in changed:
            print(f"  На екрані:    {' | '.join(changed['onscreen_text'])}")
    print("\nФайли: " + ", ".join(g["files"]))
    print(f"Позначте використані варіанти:  python -m socklock accept {g['variants'][0]['id']} ...")
    print(f"Запишіть витрачений час:        python -m socklock log-time {g['id']} <хвилини>")


def cmd_library_add(args):
    target = library.add_winner_file(config.LIBRARY_DIR, args.file)
    print(f"Додано до бібліотеки: {target}")
    return 0


def cmd_accept(args):
    accepted, unknown = storage.accept_variants(config.DB_PATH, args.ids)
    for variant_id in accepted:
        print(f"Прийнято: {variant_id}")
    for variant_id in unknown:
        print(f"Не знайдено: {variant_id}", file=sys.stderr)
    return 1 if unknown else 0


def cmd_log_time(args):
    storage.log_time(config.DB_PATH, args.generation_id, args.minutes)
    print(f"Записано {args.minutes:g} хв для {args.generation_id}")
    return 0


def cmd_import_results(args):
    summary = results.import_results(
        args.csv, config.DB_PATH, config.LIBRARY_DIR,
        min_romi=args.min_romi / 100, min_ctr_ratio=args.min_ctr_ratio,
        min_spend=args.min_spend, ltv=args.ltv,
    )
    print(f"{'Оголошення':<40} {'Група':<10} {'Spend':>10} {'CTR':>7} {'CR':>7} {'CPA':>9} {'ROMI':>8}  Переможець")
    for ad in summary["ads"]:
        mark = "ТАК" if ad["winner"] else ""
        print(f"{ad['ad_name'][:40]:<40} {GROUP_LABELS[ad['group']]:<10} {money(ad['spend']):>10} {pct(ad['ctr']):>7} "
              f"{pct(ad['cr']):>7} {money(ad['cpa']):>9} {pct(ad['romi']):>8}  {mark}")
    print()
    for name, total in summary["totals"].items():
        print(f"{GROUP_TITLES[name]:<17} оголошень: {total['ads']:<3} spend {money(total['spend'])}, "
              f"CTR {pct(total['ctr'])}, CR {pct(total['cr'])}, CPA {money(total['cpa'])}, ROMI {pct(total['romi'])}")
    print(f"Медіанний CTR контролю: {pct(summary['control_median_ctr'])}")
    if summary["value_estimated"]:
        print(f"У CSV немає колонки цінності конверсій: value = purchases x LTV ${summary['ltv']:.0f}.")
    print(f"Критерії переможця: ROMI >= {args.min_romi:g}% і CTR >= {args.min_ctr_ratio:g} x медіана контролю"
          + (f" і spend >= ${args.min_spend:g}" if args.min_spend else ""))
    print(f"Переможців: {len(summary['winners'])}")
    for path in summary["copied"]:
        print(f"  скопійовано в бібліотеку: {path}")
    for variant_id in summary["already_there"]:
        print(f"  вже в бібліотеці: {variant_id}")
    for variant_id in summary["unknown"]:
        print(f"  ID немає в базі, пропущено: {variant_id}")
    return 0


def cmd_report(args):
    print(report.format_report(report.build_report(config.DB_PATH)))
    return 0


def cmd_serve(args):
    web.serve(args.port, config.resolve_backend(args.backend, args.mock), args.model or config.DEFAULT_MODEL)
    return 0


def cmd_demo(args):
    info = demo.run_demo(config.HOME, reset=args.reset)
    g = info["generation"]
    print("Демо-дані створено:")
    print(f"  бібліотека стилю:    {info['library']}")
    print(f"  вхідний сценарій:    {info['samples'] / 'winning_script.md'}")
    print(f"  історична генерація: {g['id']} (MOCK, 6 варіантів прийнято, 110 хв)")
    print(f"  експорт Meta (CSV):  {info['csv']}")
    print("\nДалі:")
    print("  python -m socklock generate samples/winning_script.md --mock")
    print("  python -m socklock accept <ID варіантів>")
    print("  python -m socklock log-time <ID генерації> 100")
    print("  python -m socklock import-results samples/meta_export.csv")
    print("  python -m socklock report")
    return 0


# ---------------------------------------------------------------- argument parser

def add_backend_args(parser):
    parser.add_argument("--backend", choices=BACKENDS, default=None,
                        help=f"cli = локальний Claude Code (типово), api = ключ Anthropic API, mock = заглушка "
                             f"(типово: {config.DEFAULT_BACKEND}, змінна SOCKLOCK_BACKEND)")
    parser.add_argument("--mock", action="store_true", help="офлайн-заглушка (те саме, що SOCKLOCK_MOCK=1)")
    parser.add_argument("--model", default=None,
                        help=f"модель (типово {config.DEFAULT_MODEL}, змінна SOCKLOCK_MODEL), напр. claude-opus-5-5")


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m socklock",
                                     description="SockLock Hooks: варіанти текстів для відеореклами.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="згенерувати варіанти з виграшного сценарію",
                       description="Налаштування можна задати в front matter файлу (context, elements, "
                                   "variants, model); явні прапорці мають пріоритет.")
    p.add_argument("script", help="файл сценарію .md, .txt або .json")
    p.add_argument("-e", "--elements", nargs="+", choices=ELEMENTS, help="що змінювати (типово все)")
    p.add_argument("-n", type=int, default=None, help="кількість варіантів (типово 10)")
    p.add_argument("--context", default=None, help="контекст вільним текстом, напр. 'Пиши українською.'")
    p.add_argument("--product", default="", help="контекст: продукт")
    p.add_argument("--audience", default="", help="контекст: аудиторія")
    p.add_argument("--angle", default="", help="контекст: кут / ідея")
    p.add_argument("--effort", default=config.DEFAULT_EFFORT, choices=["low", "medium", "high"],
                   help="глибина міркувань моделі (типово medium)")
    p.add_argument("--show-prompt", action="store_true", help="лише показати промпт, без виклику моделі")
    add_backend_args(p)
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("library", help="бібліотека стилю")
    library_sub = p.add_subparsers(dest="library_command", required=True)
    p_add = library_sub.add_parser("add", help="додати сценарій у library/winners/")
    p_add.add_argument("file")
    p_add.set_defaults(func=cmd_library_add)

    p = sub.add_parser("accept", help="позначити варіанти, які дизайнер використав")
    p.add_argument("ids", nargs="+")
    p.set_defaults(func=cmd_accept)

    p = sub.add_parser("log-time", help="записати час на модифікацію")
    p.add_argument("generation_id")
    p.add_argument("minutes", type=float)
    p.set_defaults(func=cmd_log_time)

    p = sub.add_parser("import-results", help="імпорт CSV з Meta Ads Manager")
    p.add_argument("csv")
    p.add_argument("--min-romi", type=float, default=config.MIN_ROMI * 100, help="мінімальний ROMI у %% (типово 130)")
    p.add_argument("--min-ctr-ratio", type=float, default=1.0, help="CTR >= це x медіана контролю (типово 1.0)")
    p.add_argument("--min-spend", type=float, default=0.0, help="мінімальний spend у $ (типово 0 = вимкнено)")
    p.add_argument("--ltv", type=float, default=config.LTV_USD, help="LTV для ROMI без колонки value (типово 68)")
    p.set_defaults(func=cmd_import_results)

    p = sub.add_parser("report", help="метрики перевірки гіпотези vs пороги (PASS/FAIL)")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("serve", help="локальна вебсторінка для дизайнерів")
    p.add_argument("--port", type=int, default=8000)
    add_backend_args(p)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("demo", help="створити демо-дані для відео")
    p.add_argument("--reset", action="store_true", help="видалити старі демо-дані й створити заново")
    p.set_defaults(func=cmd_demo)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as error:
        print(f"Помилка: файл не знайдено: {error.filename}", file=sys.stderr)
        return 1
    except (ValueError, GenerationError) as error:
        print(f"Помилка: {error}", file=sys.stderr)
        return 1
