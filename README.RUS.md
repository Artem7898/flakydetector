# FlakyDetector 

**Документация FlakyDetector:** https://flakydetector.readthedocs.io/en/latest/

Автор: **Artem Alimpiev, Python Backend Developer**. Это пакет для проверки,
а не стабильный релиз, готовый multi-tenant SaaS или независимо оценённая ML-модель.

## Запуск

Linux, Python 3.12/3.13, Node.js 22. Команды выполняются в новой распаковке исходников.

```bash
uv sync --locked --extra api --extra dev --extra ml --extra github --extra docs
uv run --frozen flakydetector-serve --host 127.0.0.1 --port 8001 \
  --evidence-db "$HOME/.local/share/flakydetector/evidence-v4.db"
```

Во втором терминале: `cd dashboard_frontend`, затем `npm ci --ignore-scripts` и `npm run dev`.
Интерфейс: `http://127.0.0.1:3000`. API: `http://127.0.0.1:8001/api/docs`.

Исходники не возвращаются по умолчанию. Для локального разбора можно явно добавить
`--source-mode redacted`. Это best-effort redaction, не гарантия обнаружения любого секрета.
Права, срок просмотра, подтверждение экспорта и проверка серверной подписи применяются отдельно.

## Что добавлено

SARIF 2.1.0, идентичность находок, baseline/new-only, consumer Action, event model,
восемь monitors, управляемый quarantine, runtime-экран, метрики с явными знаменателями,
выборочная семантика AST, impact hints и claim-level triage. Детализация и ограничения:
[capability matrix](docs/CAPABILITY_MATRIX.md), [migration](docs/MIGRATION_0.2.2.md),
[security](SECURITY.md), [monitors](docs/MONITORS.md).

Подмена в недостижимой ветке больше не считается гарантированно действующей.
Анализатор работает в отдельном завершаемом Linux-процессе, но это **не sandbox файловой
системы/сети**. В shared-режиме разрешён один workspace на экземпляр; разные доверительные
области требуют отдельных ограниченных контейнеров.

Recorder подключается к вашим разрешённым тестам. Веб-сервис загруженные тесты не запускает.
Collection order не называется фактическим порядком выполнения workers. Флаги provenance
не устанавливают seed и не замораживают внешние сервисы — они фиксируют ваше описание условий.

## Проверка и публикация

Сначала проверить отдельный пакет, затем открыть PR. Не применять старый `github_publish.py`
из набора для PR №6 к этому релизу. Main и существующий CI gate не отключаются.
Ruff, Pyright, реальная матрица plugins, официальный SARIF schema test, frontend build,
Sphinx, wheel и container smoke должны пройти в полном окружении. Локальные synthetic-тесты
не заменяют эти проверки. Обновляйте frontend/backend вместе: API и feature semantics — 3.0.0.

Старый ledger schema 3 сохраняется, новые события имеют отдельную schema 1/provenance 4.
Перед миграциями делайте backup. Старые модели не становятся совместимыми автоматически.
Не заявляются независимая точность, продакшен-калибровка или успешная публикация на GitHub
Code Scanning только по наличию соответствующего кода.

## Выбор файлов (исправление 0.2.2)

Для анализа исходников нажмите **File / ZIP** в панели анализа. В диалоге видны все файлы;
после выбора принимаются только `.py` (до 1 МБ) или `.zip` (до 10 МБ). Можно перетащить файл
в область загрузки. Для папки или нескольких файлов сначала создайте ZIP. Неподдерживаемый
файл отклоняется с пояснением, а не анализируется как прежний выбранный файл.

Отдельное поле **Import execution history** служит для recorder `.jsonl`, не для Python-кода.
При отмене диалога прежний выбор сохраняется. **Clear file and return to code** возвращает
сохранённый текстовый черновик.

Версия приложения — **0.2.2**, без `rc`. API/feature schema `3.0.0`, SARIF `2.1.0` и версии
ledger/events не являются номерами приложения и в этом исправлении не меняются.
После обновления перезапустите frontend/backend; для Docker пересоберите образ. Обновите
вкладку `Ctrl+Shift+R`. Изменение номера само по себе не означает публикацию GitHub/PyPI-релиза.
