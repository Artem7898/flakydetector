> Исторический документ исправлений 0.1.0 → 0.2.0. Не является отчётом по текущему кандидату. См. [статус 0.2.1rc1](IMPLEMENTATION_STATUS.RU.md).

# Исправления FlakyDetector: решение, код и проверяемый результат

Версия исправленной поставки: **0.2.0**. Основа — предоставленный ZIP, не удалённый GitHub-репозиторий. Исходный архив сохранён без изменений. Этот документ описывает изменение поведения; фактические результаты запусков находятся в `VALIDATION.json`.

Сохранены 11 исходных unit-тестов; обращения к AST адаптированы к новому `SourceAnalysis`. Новые регрессии и интеграционные тесты проверяют исправленное поведение, а не выдают старый audit-suite с несовместимыми контрактами за неизменённый passing suite.

## Главный принцип

Приложение должно помогать искать нестабильность и объяснять evidence. Поэтому три разных утверждения больше не смешиваются:

1. «В коде есть фактор риска» — статический анализ.
2. «При сопоставимых повторных запусках тест и проходил, и падал» — наблюдаемая нестабильность.
3. «Причиной может быть X» — проверяемая человеком гипотеза.

Отсутствие паттерна не превращается в обещание стабильности. Пропущенный/неизвестный/незавершённый результат не превращается в passed. Вероятность не подменяется весом правила или расстоянием вектора.

## Порядок работ и критерии

| Этап | Сделано в коде | Чем проверить | Что нельзя считать закрытым автоматически |
|---|---|---|---|
| 0. Секреты | `.env` и Git-история исключены, пример ключей пустой, сборка по allowlist, offline release gate | `scripts/check_release.py`; отдельная проверка отсутствия исходных значений ключей | Отзыв/замена ключей у провайдера требует действий владельца |
| 1. Поставка | Рабочие wheel/entry point, multipart, один сервис CLI/API, loader manifest, CI corpus, Docker/Compose | `test_four_adapters_same_corpus`, `scripts/wheel_smoke.py`, отдельная установка wheel | Docker/удалённый CI считаются выполненными только после реального запуска соответствующего окружения |
| 2. Достоверность | 42D схема, корректные фазы, provenance, отдельные исходы, явные ошибки/неполнота | `test_regressions.py`, `test_execution_evidence.py`, model/schema tests | Нельзя утверждать accuracy/calibration без подходящего benchmark |
| 3. Правила | Лексический контекст, aliases, async, точные mocks/resources, fixture graph и shallow trap | Парные и metamorphic tests; `LIMITATIONS.md` | Динамический Python/наследование/plugin metadata не объявлены полностью поддержанными |
| 4. Контракты | GitHub DTO/redirect, SQLite lifetime, API/UI v2, лимиты, bounded workers, lint/types/gates | Integration tests, frontend contract tests, Ruff/Pyright, wheel smoke | Live GitHub и поведение в production deployment не выводятся из MockTransport-тестов |
| 5. Интеллект | Проверяемый и возобновляемый LLM, evidence IDs, недеструктивный RAG, benchmark pipeline | Fake adapters, schema rejection, temporary model roundtrip | Не обучена новая рабочая `.cbm`; реальная эффективность LLM/RAG не измерена |

## Почему выбран этот путь

### Один сервис решения вместо нескольких вердиктов

Раньше JSON и ZIP могли по-разному объявить один тест flaky. Теперь transport только проверяет вход и вызывает `AnalyzeService`.

```python
response = service.analyze(
    bundle.sources,
    diagnostics=bundle.diagnostics,
    use_ml=use_ml,
)
```

`SourceAnalysis` заменяет неоднозначный tuple: `patterns`, `fixtures`, `tests`, `diagnostics`. Ошибка парсинга остаётся значением результата и сохраняет путь/строку. `AnalysisResponse.status` показывает `ok`, `partial` или `error`, а не только список найденных проблем. Это изменение публичного контракта; обратная совместимость с некорректным `flaky_probability` намеренно не имитируется.

### Итог теста после teardown

Проходящая call-фаза не отменяет ошибки подготовки или очистки. В `storage.py` сохраняется каждая фаза, а финальная запись вычисляется так:

```python
terminal = self._terminal(reports) if phase == "teardown" else "incomplete"
```

Сбой setup/teardown имеет приоритет `error`; сбой call — `failed`; skip/xfail/xpass остаются отдельными. Запись до завершения не признаётся успешной. У plugin-recorder `eq=False`: pytest регистрирует конкретный объект плагина, поэтому ему нужна идентичность, а не сравнение изменяемого dataclass по полям. Реальные subprocess-тесты проверили последовательный запуск и xdist.

### Единая схема признаков и запрет старой модели

Вместо отдельной вручную собранной матрицы обучение и serving используют один `FeatureExtractor` и `FEATURE_NAMES`. Считаются AST/log counts, агрегаты, категории и только применимые к тесту фикстуры. Batch не теряет fixture features.

```python
features = tuple(values[name] for name in FEATURE_NAMES)
```

Манифест модели содержит версию семантики, порядок имён, hash схемы, checksum файла и provenance датасета. При несовпадении загрузка прекращается с конкретным статусом. Совпадение размерности 42 само по себе недостаточно: старые 42 столбца имели другую семантику. Резервный `ast_float_comparison` не используется для ложного правила про корректный `assertAlmostEqual`.

Отсутствие `yield` не объявляется причиной flakiness. Fixture scope и изменяемость рассматриваются как evidence риска общего состояния. Early stopping сохранён. Временная игрушечная модель в тесте проверяет только корректность сериализации; её artifact не входит в релиз и запрещён application inference по умолчанию.

### Лексический анализ и точная область действия

Вместо повторного обхода всех вложенных функций используется один visitor с контекстом функции/класса и таблицей aliases. Парные тесты проверяют одинаковый сигнал после переименования import, отсутствие двойного подсчёта и различие локальной/модульной мутации.

`with unrelated()` не делает каждый вложенный `open()` безопасным. `patch("time.time")` не превращает `requests.get()` в mocked. Контекст patch заканчивается при выходе из соответствующего блока. Такие локальные правила проще проверить и честно ограничить, чем выдавать поверхностные эвристики за полноценное доказательство отсутствия гонок.

Fixture graph учитывает предков `conftest.py`, зависимости, autouse и override. Неиспользованная fixture не попадает в признаки теста. Цикл, неизвестная fixture или dynamic scope дают diagnostics. Ограничения data-flow, plugin fixtures, inherited collection и cross-module helpers перечислены отдельно.

### Безопасная поставка и явная деградация

ZIP читается без распаковки на диск. Проверяются пути, дубликаты, symlink, количество файлов, размер, степень сжатия и кодировка. API ограничивает body до обработки FastAPI; CPU-анализ передаётся в ограниченный executor. Timeout не освобождает слот незавершённой задачи, поэтому очередь не растёт бесконтрольно.

Минимальная установка не тащит CatBoost/Chroma/SDK/GPU. Опциональные зависимости находятся в extras, адаптеры загружаются по требованию. Это исправляет startup и снижает число причин, по которым статический анализ может не запуститься. Отсутствующая запрошенная модель даёт `partial` с причиной и сохраняет evidence правил.

### Объяснения, а не выдуманные доказательства

LLM получает точные `passed/failed/ignored` из записи наблюдений. Выход проверяется Pydantic-схемой; evidence IDs должны существовать во входе, а предложенный код — парситься. Это проверяет структуру и ссылочную целостность, но **не доказывает истинность объяснения**. Код модели никогда не исполняется.

RAG сохраняет объяснение, рекомендацию, repo/nodeid/source hash и evidence IDs. Возвращается `distance` с `metric="cosine"`, без процентов. Новая коллекция сначала полностью строится, проверяется, затем `active.json` атомарно переключается; сбой не удаляет текущий индекс.

## Матрица F01–F25

| Finding | Исправление | Основное доказательство |
|---|---|---|
| F01 | Очищенный allowlist archive; ключи не переносятся | release gate + проверка исходных значений; rotation отдельно |
| F02 | `packages=["src/flakydetector"]`, существующий `cli:main` | build из sdist, install вне checkout |
| F03 | `api` extra включает multipart; lazy ML | API startup в wheel environment |
| F04 | Единый `SourceAnalysis`, обновлены callers | исходные AST tests + parity |
| F05 | Реальный `tests/corpus`, CLI severity/exit code | `test_cli_exit_codes`, workflow scan |
| F06 | Признаки заполняются, batch сохраняет fixture context | `test_features_filled_and_batch_preserves_used_fixtures` |
| F07 | Проверяемый manifest/load; ошибки не маскируются | roundtrip, checksum/schema/demo rejection |
| F08 | Прежние quality claims отозваны, repository split и baselines | clone/monoclass/review gates; реальный benchmark впереди |
| F09 | Один verdict/risk policy для transport | four-adapter parity |
| F10 | Phase ledger и финализация teardown, isolated recorder | реальные pytest + xdist tests |
| F11 | Удалён второй 45D/leaky pipeline, один экспорт | records/feature schema tests |
| F12 | `MutableMapping` proxy, корректное удаление/reset | state-trap paired operations |
| F13 | Явные parse/empty/limit errors | negative API/ZIP tests |
| F14 | Async/aliases/lexical attribution/mock/resource scope | `test_regressions.py` |
| F15 | Определения и применение fixture разделены | graph dependency/override/cycle tests |
| F16 | Explicit outcomes/full node IDs, runs считаются по запускам | log regression tests |
| F17 | GitHub DTO, bounded streamed redirects без передачи auth | MockTransport nested shape/redirect/errors |
| F18 | `try/finally close`, schema migration/short transaction | connection closed + legacy migration |
| F19 | repo/source/env identity, async/class/param source | export/extraction/fingerprint tests |
| F20 | Точные fail counts, schema/evidence checks, resume | LLM fake-provider tests |
| F21 | Metadata сохранены, cosine distance, atomic active index | RAG rebuild failure preserves index |
| F22 | Non-editable locked Docker build, frontend dist, Compose | source исправлен; см. фактический статус в VALIDATION |
| F23 | AnalyzeService + protocol boundaries + injected clients | adapter/service integration tests |
| F24 | UI показывает все tests/locations/diagnostics/degraded/null | frontend contract tests, backend-generated example |
| F25 | Ruff config, strict Pyright, обязательные gates и чистая wheel-поставка | журнал локальных gates и workflow |

## Практики разработки

Использованы подходы, применимые к современной Python-разработке 2025 года: Python 3.12 type parameters, `Protocol` на внешних границах, Pydantic v2, `frozen/slots/kw_only` там, где нужны value objects; dependency injection, единый application service, lockfile, non-editable wheel, короткие транзакции, атомарное переключение artifacts, контрактные/парные/metamorphic tests. Это конкретные проверяемые решения, а не замена исправления модными библиотеками.

`frozen` не объявляется глубокой неизменяемостью произвольных вложенных словарей. Thread timeout не объявляется process isolation. Fake adapters не объявляются live integrations. Прошедшие регрессионные тесты не объявляются доказательством отсутствия всех ошибок.

## Что потребуется после этой поставки

1. Отозвать старые ключи у провайдера, проверить журнал их использования и подключить новые через секреты окружения.
2. Прогнать добавленный workflow в целевом репозитории, включая Docker и Python 3.13, если соответствующего фактического результата нет в `VALIDATION.json`.
3. Собрать независимо размеченный корпус сопоставимых runs по опубликованному протоколу; провести calibration/reliability и repository-level uncertainty review. Только затем оценивать новую рабочую модель.
4. Расширять поддержку динамических fixture/call-graph случаев отдельными парными тестами, не меняя неизвестное состояние на успешное.
