# SockLock Hooks — MVP

Інструмент, який із виграшного сценарію відеореклами робить готові варіанти текстів (хук, перші рядки, текст на екрані) з унікальними ID для Meta, зберігає все в локальну базу і рахує результати перевірки гіпотези.

## Яку проблему вирішує

SockLock продає магнітні шкарпетки за підпискою (5 пар за $29, далі поповнення щокварталу). Майже весь трафік — Meta Ads, основний ринок — США. 6 моушн-дизайнерів роблять ~240 «модифікацій» виграшних відеокреативів на місяць. Одна модифікація займає ~3 год, і ~половина цього часу — ручна робота з текстом: переписати хук, перші рядки та текст на екрані з виграшного сценарію. Щоб вийти на $800k рекламного бюджету на місяць, потрібно ~500 модифікацій на місяць. Інструмент дає дизайнерам готові варіанти текстів, щоб модифікація займала ~2 год.

Повна версія буде Slack-ботом. Цей MVP працює з першого дня **без доступу до інфраструктури SockLock** (без Slack, Meta API та Airtable): на вході текст, файли або CSV, на виході — результат. Тому це Python CLI плюс маленька локальна вебсторінка.

## Як працює генерація: три backend-и

| Backend | Що це | Що потрібно |
|---|---|---|
| `cli` (типово) | Локальний Claude Code CLI (`claude -p`) на підписці Claude студента | встановлений Claude Code і вхід в акаунт |
| `api` | Офіційний Python SDK `anthropic` з API-ключем | `ANTHROPIC_API_KEY` (для майбутнього продакшн-бота) |
| `mock` | Офлайн-заглушка для тестів і демо, **не** текст від Claude | нічого |

`--mock` вмикається тільки явно (`--mock`, `--backend mock` або `SOCKLOCK_MOCK=1`). Якщо справжня модель недоступна, програма показує помилку і **ніколи** тихо не підставляє заглушку.

## Встановлення

```bash
cd socklock-hooks-mvp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`requirements.txt` містить `anthropic` і `pytest`. Пакет `anthropic` потрібен **тільки** для `--backend api`; backend `cli` і `--mock` працюють без нього (він імпортується лише всередині api-backend-у).

Для backend-у `cli` (типового) потрібен Claude Code:

```bash
# встановлення: https://claude.com/claude-code
claude            # перший запуск, у ньому виконайте /login (акаунт з підпискою Claude)
claude auth status   # має показати "loggedIn": true
```

## Запуск

Усі команди виконуються з папки проєкту. Після клонування репозиторію **спершу** запустіть `demo --reset`: він створює `library/`, `samples/`, `data/` і `out/` (у git їх немає; джерела демо-файлів лежать у `socklock/demo_data/`).

```bash
# 1. Демо-дані: бібліотека стилю, приклад сценарію, історична генерація, CSV з Meta
.venv/bin/python -m socklock demo --reset

# 2. Генерація (типово: backend cli, модель claude-sonnet-5-5, 10 варіантів, усі елементи)
.venv/bin/python -m socklock generate samples/winning_script.md --product "SockLock magnetic socks" --audience "US moms 28-45"
.venv/bin/python -m socklock generate samples/winning_script.md -e hook onscreen_text -n 5
.venv/bin/python -m socklock generate samples/winning_script.json --model claude-opus-5-5   # порівняти з Opus
.venv/bin/python -m socklock generate samples/winning_script.md --mock                     # офлайн
.venv/bin/python -m socklock generate samples/winning_script.md --show-prompt              # лише показати промпт
.venv/bin/python -m socklock generate socklock/demo_data/examples/uk_laundry_day.md          # налаштування з front matter
.venv/bin/python -m socklock generate socklock/demo_data/examples/uk_laundry_day.md -n 3 --context "Write in English."

# 3. Дизайнер позначає використані варіанти і час на модифікацію
.venv/bin/python -m socklock accept SLM-20261109-K7QX-v1 SLM-20261109-K7QX-v4
.venv/bin/python -m socklock log-time SLM-20261109-K7QX 95

# 4. Імпорт експорту з Meta Ads Manager -> метрики, переможці потрапляють у library/winners/
.venv/bin/python -m socklock import-results samples/meta_export.csv
.venv/bin/python -m socklock import-results export.csv --min-romi 140 --min-ctr-ratio 1.1 --min-spend 200

# 5. Звіт перевірки гіпотези: PASS/FAIL по кожній метриці
.venv/bin/python -m socklock report

# 6. Вебсторінка для дизайнерів (http://127.0.0.1:8000): темна тема, «Приклади», імпорт файлу
.venv/bin/python -m socklock serve
.venv/bin/python -m socklock serve --mock --port 8080

# Додати свій виграшний сценарій у бібліотеку
.venv/bin/python -m socklock library add my_winner.md

# Тести
.venv/bin/python -m pytest
```

Налаштування через змінні середовища: `SOCKLOCK_BACKEND` (cli/api/mock), `SOCKLOCK_MODEL` (напр. `claude-opus-5-5`; backend `cli` приймає й аліаси `sonnet`/`opus`), `SOCKLOCK_EFFORT` (low/medium/high, типово medium), `SOCKLOCK_MOCK=1`, `SOCKLOCK_HOME` (де лежать `library/`, `data/`, `out/`, `samples/`; типово папка проєкту).

### Формат сценарію

Markdown (кожна сцена починається з `##`):

```markdown
# Laundry day rescue (UGC, 20 s)

## Scene 1
Visual: Woman pulls a tangled pile of single socks out of the dryer
VO: Every laundry day I lose at least one sock.
On-screen: WHERE DO THEY EVEN GO
```

Або JSON: `{"title": "...", "scenes": [{"visual": "...", "voiceover": "...", "onscreen_text": "..."}]}`. Приймаються й інші назви полів: `line`, `vo`, `on_screen_text`, `text`, `ost` тощо.

**Налаштування у файлі (front matter).** На початку `.md`/`.txt` можна додати блок `key: value` між рядками `---`; у JSON — ті самі ключі на верхньому рівні. Один і той самий файл працює і в CLI, і у вебсторінці (кнопка «Імпортувати сценарій» або перетягування файлу на поле сценарію).

```markdown
---
context: Продукт: магнітні шкарпетки SockLock, 5 пар за $29. Пиши українською.
elements: hook, first_lines, onscreen_text
variants: 10
model: claude-sonnet-5-5
---
# День прання без втрат (UGC, 20 с)
## Scene 1
...
```

Невідомі ключі ігноруються, для відсутніх лишаються типові значення. У CLI явні прапорці (`-n`, `-e`, `--model`, `--context`) мають пріоритет над front matter. Шість готових прикладів (3 англійською, 3 українською для тестування) лежать у `socklock/demo_data/examples/`; у вебсторінці вони є в списку «Приклади».

Що означають елементи: **hook** — озвучка сцени 1 (перші ~3 секунди), **first_lines** — озвучка сцен 2–3, **onscreen_text** — текст на екрані в кожній сцені. Візуал і решта озвучки ніколи не змінюються.

### Що виходить

- У терміналі — компактний список варіантів з ID і зміненими текстами.
- `out/<ID генерації>.md` і `.json` — повні сценарії всіх варіантів у тій самій структурі.
- `data/socklock.db` (SQLite) — кожна генерація: вхідний сценарій, варіанти, ID, час, модель, backend, токени.
- ID варіанта має вигляд `SLM-20261109-K7QX-v3`; його вставляють у назву оголошення в Meta, напр. `UGC laundry | SLM-20261109-K7QX-v3 | US | 9x16`.

Приклад справжньої відповіді Claude (backend `cli`, Sonnet 5.5): `examples/real_cli_output_SLM-20261109-KAA6.md`.

## Як вимірюємо успіх

**Перевірка гіпотези:** 2 дизайнери працюють з інструментом 2–4 тижні, інші 4 — контрольна група (працюють як раніше). Креативи, зроблені з інструментом, отримують ID у назві оголошення, тому в експорті Meta їх можна відрізнити від контрольних.

| Метрика | Як рахуємо в інструменті | Поріг |
|---|---|---|
| Acceptance rate | прийняті варіанти (`accept`) ÷ згенеровані | ≥ 50% |
| Час на модифікацію | середнє з `log-time`, хв | ≤ 120 хв (≤ 2 год) |
| CTR варіантів інструменту | CTR групи перевірки (оголошення з ID) vs контрольної групи, з `import-results` | не нижче контролю |
| ROMI варіантів інструменту | цінність конверсій ÷ spend групи перевірки | ≥ 130% |

Формули: CTR = clicks ÷ impressions, CR = purchases ÷ clicks, CPA = spend ÷ purchases, ROMI = conversion value ÷ spend (як у брифі; якщо в CSV немає колонки цінності — purchases × LTV $68). Метрики групи рахуються на сумах (зважено за обсягом). Переможець = оголошення групи перевірки з ROMI ≥ 130% і CTR ≥ медіанного CTR контролю (пороги налаштовуються прапорцями).

**Бізнес-ціль:** 240 → 360 модифікацій на місяць тим самим складом (з 3 год до 2 год на модифікацію), що дає +$115k рекламного бюджету і ~+$34k очікуваного EGP на місяць. `report` показує прогноз: 240 × 180 хв ÷ виміряний середній час.

**Терміни:** метрики з таблиці вище оцінюємо після 2–4 тижнів перевірки гіпотези. Бізнес-ціль (240 → 360 модифікацій/міс, +$115k бюджету, ~+$34k EGP/міс) вимірюємо за перший повний місяць після розгортання інструменту на всю команду.

## Наступна ітерація

- **Slack-бот:** дизайнер кидає сценарій у Slack і отримує варіанти з ID; `accept` і час — кнопками.
- **API-backend з ключем для всієї команди:** MVP працює на локальній підписці Claude Code одного користувача; продакшн-бот для команди перемикається на `--backend api` (офіційний SDK `anthropic`, ключ організації, кешування промпту, server-side fallback). Код backend-у вже є в `socklock/backends.py`.
- **Пряма інтеграція з Meta Ads API та Airtable**, якщо дадуть доступ: результати оголошень підтягуються автоматично замість ручного CSV.
- **A/B Sonnet vs Opus за acceptance rate:** модель уже налаштовується (`--model`), а `report` показує acceptance окремо по кожній моделі.
- **Автонавчання на переможцях:** зараз переможці копіюються в бібліотеку; далі — відбір найкращих прикладів у промпт, вага за свіжістю, ротація старих.

## Обмеження MVP

- Backend `cli` використовує підписку одного користувача на цьому комп'ютері: ліміти підписки, не для всієї команди.
- Backend `api` перевірено лише тестами з фейковим клієнтом (API-ключа немає).
- Запускайте зі звичайного терміналу: виклик `claude -p` зсередини іншої сесії Claude Code не перевірявся.
- Кожен `import-results` замінює попередній імпорт (експорт Ads Manager кумулятивний). Числа в CSV — у форматі США (крапка як десятковий роздільник).
- Переможці визначаються по оголошеннях без статистичного тесту; для малих бюджетів використовуйте `--min-spend`.
- Усі переможці потрапляють у промпт; коли їх стане багато, потрібен відбір (див. «Наступна ітерація»).
- Для справжньої перевірки гіпотези почніть з чистої бази (видаліть `data/` і `out/`) і покладіть у `library/` справжній стайлгайд і переможців — демо-дані містять mock-тексти.
