# Перенос системы отчетности по платежам в Inventory_service_1

Этот документ является одновременно техническим ТЗ, переносом знаний из проекта `Reconciliation` и стартовым промптом для реализации платежной отчетности в проекте `Inventory_service_1`.

Цель: построить постоянную систему загрузки платежей из SalesDrive, хранения в БД, мапинга контрагентов на поставщиков, отчетов по входящим и исходящим платежам, движения по расчетным счетам предприятий, веб-интерфейса и экспорта отчетов в Excel.

## Что есть в текущем проекте

Текущий проект `Reconciliation` уже умеет:

- загружать платежи из SalesDrive API за период;
- отдельно получать `incoming`, `outcoming` или оба типа платежей;
- нормализовать платежи в единую модель;
- классифицировать входящие платежи;
- определять внутренние перемещения между собственными счетами;
- мапить исходящие платежи на поставщиков по контрагенту;
- формировать Excel monthly payment report;
- показывать непопавших в мапинг контрагентов;
- частично использовать supplier reconciliation, но для нового проекта эту часть надо отделить от базовой платежной отчетности.

Последний проверенный запуск:

```bash
.venv/bin/python -m scripts.run_payment_analysis --type all --month 2026-04 --output reports/payment_report_2026_04.xlsx
```

Результат за апрель 2026:

- входящие платежи: `110`;
- исходящие платежи: `133`;
- не замапленные контрагенты: `1`;
- файл: `reports/payment_report_2026_04.xlsx`.

## Источники логики в Reconciliation

При переносе ориентироваться на эти файлы:

- `src/payment_analysis/clients/salesdrive_client.py` - клиент SalesDrive API;
- `src/payment_analysis/services/payment_loader.py` - загрузка incoming/outcoming;
- `src/payment_analysis/services/payment_normalizer.py` - нормализация полей;
- `src/payment_analysis/models/payments.py` - текущая модель платежа;
- `src/payment_analysis/services/payment_filters.py` - классификация входящих оплат;
- `src/payment_analysis/services/internal_transfer_detector.py` - внутренние переводы;
- `src/payment_analysis/services/payment_mapper.py` - мапинг контрагент -> поставщик;
- `src/payment_analysis/reports/excel_report.py` - структура текущего Excel-отчета;
- `config/analysis_settings.yaml` - правила входящих клиентских платежей;
- `config/internal_transfer_rules.yaml` - собственные счета и правила внутренних переводов;
- `data/mappings/counterparty_to_supplier.yaml` - стартовый мапинг поставщиков;
- `docs/payment_api_analysis.md` - структура ответа SalesDrive API.

## SalesDrive API

Использовать endpoint:

```text
GET {SALESDRIVE_BASE_URL}/api/payment/list/
```

Параметры:

- `type`: `incoming` или `outcoming`;
- `filter[date][from]`: дата начала, например `2026-04-01 00:00:00`;
- `filter[date][to]`: дата конца, например `2026-04-30 23:59:59`;
- `page`: номер страницы;
- `limit`: максимум `100`.

Настройки окружения:

- `SALESDRIVE_BASE_URL`;
- `SALESDRIVE_API_KEY`;
- `SALESDRIVE_TIMEOUT_SECONDS`, дефолт `30`;
- `SALESDRIVE_PAGE_LIMIT`, дефолт `100`;
- `SALESDRIVE_RATE_LIMIT_RETRY_SECONDS`, дефолт `65`;
- `SALESDRIVE_RATE_LIMIT_MAX_RETRIES`, дефолт `2`.

В новом проекте API key не хранить в коде и не переносить в документ. Использовать `.env`, secret manager или переменные окружения.

Top-level поля ответа:

- `status`;
- `data`;
- `pagination`;
- `totals`.

Поля одного платежа, которые уже реально приходили из SalesDrive:

- `id`;
- `date`;
- `type`;
- `sum`;
- `comment`;
- `purpose`;
- `nds`;
- `payerTypeId`;
- `createdAt`;
- `updatedAt`;
- `responsibleId`;
- `integrationTypeId`;
- `userId`;
- `documentItems`;
- `paymentBreakdown`;
- `counterparty.id`;
- `counterparty.egrpou`;
- `counterparty.title`;
- `organization.id`;
- `organization.egrpou`;
- `organization.title`;
- `organizationAccount.id`;
- `organizationAccount.title`;
- `organizationAccount.accountNumber`.

Важные замечания:

- валюта в item-level payload отсутствует, для текущей логики можно считать UAH или выводить валюту из счета;
- item-level статус платежа отсутствует, `status` на верхнем уровне является статусом API-ответа, а не платежа;
- `comment` часто пустой;
- бизнес-смысл обычно находится в `purpose`;
- иногда `counterparty` может быть неполным, тогда часть информации надо искать в `purpose`.

## Нормализованная модель платежа

В `Inventory_service_1` нужна нормализованная таблица платежей поверх сырого SalesDrive payload.

Логические поля:

- `id` - внутренний id записи;
- `source_system` - всегда `salesdrive`;
- `source_payment_id` - SalesDrive `id`;
- `payment_type` - `incoming` или `outcoming`;
- `payment_date` - SalesDrive `date`;
- `amount` - SalesDrive `sum`, decimal;
- `currency` - nullable, по умолчанию можно `UAH`;
- `counterparty_name` - `counterparty.title`;
- `counterparty_tax_id` - `counterparty.egrpou`;
- `comment` - SalesDrive `comment`;
- `purpose` - SalesDrive `purpose`;
- `organization_name` - `organization.title`;
- `organization_tax_id` - `organization.egrpou`;
- `account_reference` - `organizationAccount.accountNumber`;
- `raw_status` - nullable;
- `supplier_id` - nullable, результат мапинга;
- `incoming_category` - `customer_receipt`, `excluded_receipt`, `internal_transfer`, `unknown_incoming`;
- `is_internal_transfer` - boolean;
- `internal_transfer_pair_id` - nullable;
- `internal_transfer_reason` - nullable;
- `mapping_source` - например `manual_exact`, `manual_contains`, `yaml_import`, `auto`;
- `raw_payload` - JSONB;
- `import_run_id`;
- `created_at`;
- `updated_at`.

Правила нормализации:

- `payment_id` брать из `id`;
- `payment_date` брать из `date`;
- `amount` брать из `sum`;
- `comment` хранить отдельно, но для классификации использовать `comment + purpose`;
- `counterparty_name` брать из `counterparty.title`;
- `counterparty_tax_id` брать из `counterparty.egrpou`;
- `organization_name` брать из `organization.title`;
- `organization_tax_id` брать из `organization.egrpou`;
- `account_reference` брать из `organizationAccount.accountNumber`;
- сохранять полный `raw_payload`, чтобы не потерять поля при изменениях SalesDrive.

## Предлагаемая схема БД

Минимальный набор таблиц:

### `payment_import_runs`

История загрузок.

- `id`;
- `source_system`;
- `period_from`;
- `period_to`;
- `payment_type`;
- `status`;
- `started_at`;
- `finished_at`;
- `incoming_count`;
- `outcoming_count`;
- `error_message`;
- `request_params` JSONB.

### `salesdrive_payments`

Основная таблица нормализованных платежей.

Ключевая уникальность:

```text
unique(source_system, source_payment_id, payment_type)
```

Хранить поля из раздела "Нормализованная модель платежа".

### `business_accounts`

Собственные расчетные счета/карты предприятий.

- `id`;
- `account_number`;
- `label`;
- `business_entity_name`;
- `business_entity_tax_id`;
- `card_mask`;
- `currency`;
- `is_active`.

Стартовые счета из текущего проекта:

| account_number | label | card_mask |
| --- | --- | --- |
| `UA793220010000026000370005752` | `Mono main` |  |
| `UA663220010000026202324004240` | `Card 9227` | `444111******9227` |
| `UA913220010000026208323546134` | `Card 9661` | `444111******9661` |
| `UA839358710000067321000080261` | `FOP main` |  |

Собственные юрлица/ФОП:

- `ФОП Петренко Ірина Анатоліївна`;
- `Петренко Ірина Анатоліївна`;
- `Петренко`;
- `Petrenko Iryna`;
- tax id `3254110820`.

### `internal_transfer_pairs`

Найденные пары внутренних переводов.

- `id`;
- `pair_key`;
- `outcoming_payment_id`;
- `incoming_payment_id`;
- `amount`;
- `outcoming_account`;
- `incoming_account`;
- `outcoming_date`;
- `incoming_date`;
- `reason`;
- `created_at`.

### `suppliers`

Справочник поставщиков.

- `id`;
- `name`;
- `normalized_name`;
- `is_active`.

### `counterparty_supplier_mappings`

Управляемый мапинг контрагентов на поставщиков.

- `id`;
- `counterparty_pattern`;
- `match_type`: `exact` или `contains`;
- `supplier_id`;
- `priority`;
- `is_active`;
- `valid_from`;
- `valid_to`;
- `notes`;
- `created_by`;
- `updated_by`;
- `created_at`;
- `updated_at`.

Стартовый мапинг из текущего проекта:

| supplier | aliases |
| --- | --- |
| `DSN` | `Вильчаган`, `ТОВ Вильчаган` |
| `BIOTUS` | `Биотус`, `BIOTUS` |
| `ZOSIMOV` | `Зосимов` |

### `account_balance_adjustments`

Месячные ручные корректировки остатков по расчетным счетам.

- `id`;
- `account_id`;
- `period_month`;
- `opening_balance_adjustment`;
- `closing_balance_adjustment`;
- `actual_opening_balance`;
- `actual_closing_balance`;
- `comment`;
- `created_by`;
- `approved_by`;
- `created_at`;
- `updated_at`.

Назначение: раз в месяц вручную зафиксировать или скорректировать расчетные остатки, если фактический банковский остаток не совпал с расчетным.

### `account_daily_balances`

Можно сделать materialized table или view.

- `account_id`;
- `balance_date`;
- `opening_balance`;
- `incoming_amount`;
- `outcoming_amount`;
- `internal_incoming_amount`;
- `internal_outcoming_amount`;
- `external_incoming_amount`;
- `external_outcoming_amount`;
- `closing_balance`;
- `calculated_at`.

## Правила входящих платежей

Категории:

- `customer_receipt` - клиентская входящая оплата;
- `excluded_receipt` - входящий платеж, который не считать клиентской оплатой;
- `internal_transfer` - внутреннее перемещение;
- `unknown_incoming` - оставить как резерв, хотя текущая логика по умолчанию относит неизвестные входящие к клиентским.

Текущие правила включения в клиентские оплаты:

- если контрагент содержит `НоваПей`;
- если `comment + purpose` содержит `платежам, прийнятим від населення`.

Текущие правила исключения:

- если контрагент содержит `Петренко`;
- если `comment + purpose` содержит:
  - `повернення`;
  - `повернення коштів`;
  - `refund`;
  - `refunds`;
  - `chargeback`;
  - `чарджбек`;
  - `внутрішн`;
  - `власний рахунок`.

Важно: в текущем проекте после проверок исключения и включения все остальные входящие платежи возвращаются как `customer_receipt`. В новом проекте лучше сделать это настраиваемым параметром:

- строгий режим: неизвестные входящие становятся `unknown_incoming`;
- совместимый режим: неизвестные входящие становятся `customer_receipt`.

Для старта использовать совместимый режим.

## Правила внутренних перемещений

Текущие настройки:

- `require_pair_match: true`;
- `pairing_window_minutes: 5`;
- `allow_direct_self_markers_without_pair: true`.

Внутренний перевод определяется так:

1. Платеж должен быть связан с собственным счетом.
2. В тексте платежа есть маркер собственного юрлица/ФОП, налогового номера или фразы внутреннего перевода.
3. Для пары `outcoming` -> `incoming` суммы должны совпадать.
4. Счета должны быть разными.
5. Оба счета должны быть собственными.
6. Пара счетов должна быть разрешена.
7. Разница во времени должна быть не больше `5` минут.
8. Если пары нет, но есть прямой self-marker и счет собственный, платеж можно пометить внутренним без пары.

Разрешенные пары счетов:

| from_account | to_account |
| --- | --- |
| `UA839358710000067321000080261` | `UA793220010000026000370005752` |
| `UA793220010000026000370005752` | `UA839358710000067321000080261` |
| `UA839358710000067321000080261` | `UA663220010000026202324004240` |
| `UA663220010000026202324004240` | `UA839358710000067321000080261` |
| `UA839358710000067321000080261` | `UA913220010000026208323546134` |
| `UA913220010000026208323546134` | `UA839358710000067321000080261` |
| `UA793220010000026000370005752` | `UA663220010000026202324004240` |
| `UA663220010000026202324004240` | `UA793220010000026000370005752` |
| `UA793220010000026000370005752` | `UA913220010000026208323546134` |
| `UA913220010000026208323546134` | `UA793220010000026000370005752` |

Self-transfer phrases:

- `власний рахунок`;
- `перерахування коштів на інший власний рахунок`;
- `від: фоп петренко`.

Direct self markers:

- `petrenko iryna`;
- `фоп петренко ірина анатоліївна`.

## Мапинг контрагентов на поставщиков

Мапинг должен жить в БД и редактироваться через веб.

Алгоритм:

1. Для каждого внешнего исходящего платежа взять `counterparty_name`.
2. Применить активные правила из `counterparty_supplier_mappings`, отсортированные по `priority`.
3. Если `match_type = exact`, сравнить нормализованное имя полностью.
4. Если `match_type = contains`, проверить вхождение паттерна в имя контрагента.
5. Если правило найдено, записать `supplier_id` и `mapping_source`.
6. Если правило не найдено, показать контрагента в отчете `unmapped`.

Веб-интерфейс мапинга должен уметь:

- показывать список unmapped контрагентов за выбранный период;
- показывать количество платежей и сумму по каждому unmapped контрагенту;
- создавать правило мапинга из unmapped строки;
- выбирать существующего поставщика или создать нового;
- задавать `exact` или `contains`;
- задавать приоритет;
- отключать правило;
- видеть историю изменений;
- пересчитать мапинг за выбранный период после изменения правил.

Регламент:

- обновлять мапинг периодически, когда появляются unmapped контрагенты;
- перед закрытием месяца пройти список unmapped и назначить поставщиков;
- после обновления мапинга пересчитать отчеты за месяц.

## Движение по счетам предприятий

Нужно строить отчет по каждому расчетному счету/карте:

- начальный остаток;
- входящие платежи;
- исходящие платежи;
- внутренние входящие;
- внутренние исходящие;
- внешние входящие;
- внешние исходящие;
- конечный расчетный остаток;
- ручная корректировка;
- фактический закрывающий остаток.

Расчет:

```text
closing_balance =
  opening_balance
  + incoming_amount
  - outcoming_amount
  + manual_adjustments
```

Внутренние переводы в отчете движения по счетам показывать обязательно, потому что они меняют остатки конкретных счетов. Но в отчете доходов/клиентских поступлений и оплат поставщикам внутренние переводы надо исключать.

Месячный процесс:

1. Загрузить платежи за месяц.
2. Определить внутренние переводы.
3. Применить мапинг поставщиков.
4. Построить расчетные остатки.
5. Сравнить с фактическими банковскими остатками.
6. Внести `account_balance_adjustments`.
7. Пересчитать отчет.
8. Закрыть период.

## Веб-отчеты

Нужны фильтры:

- период: день, неделя, месяц, произвольный диапазон;
- тип платежа: incoming/outcoming/all;
- счет/предприятие;
- поставщик;
- категория входящих;
- внутренние/внешние;
- mapped/unmapped.

Минимальные страницы:

1. `Платежи`
   - таблица всех платежей;
   - фильтры;
   - просмотр raw payload;
   - признак внутреннего перевода;
   - поставщик;
   - категория входящего.

2. `Сводка`
   - входящие всего;
   - клиентские входящие;
   - исключенные входящие;
   - внутренние входящие;
   - исходящие всего;
   - внешние исходящие;
   - внутренние исходящие;
   - исходящие, сопоставленные с поставщиками;
   - исходящие без мапинга.

3. `Оплаты поставщикам`
   - группировка по поставщикам;
   - количество платежей;
   - сумма;
   - детализация по платежам;
   - unmapped контрагенты.

4. `Входящие оплаты клиентов`
   - все клиентские входящие;
   - группировка по дням;
   - группировка по счетам;
   - исключенные платежи отдельно.

5. `Движение по счетам`
   - по каждому счету;
   - начальный остаток;
   - входящие;
   - исходящие;
   - внутренние перемещения;
   - внешний cash flow;
   - расчетный конечный остаток;
   - фактический конечный остаток;
   - разница.

6. `Мапинг`
   - список правил;
   - unmapped;
   - создание/редактирование правил;
   - пересчет периода.

7. `Импорты`
   - история загрузок SalesDrive;
   - статус;
   - ошибки;
   - повторить импорт.

## Excel-экспорт

Excel должен быть экспортом веб-отчета, а не отдельной логикой. Один и тот же backend query/service должен кормить и веб, и Excel.

Листы из текущего отчета, которые стоит сохранить:

- `summary_Сводка`;
- `receipts_Все`;
- `receipts_Клиенты`;
- `receipts_Искл`;
- `incoming_Все`;
- `incoming_Внутр`;
- `outgoing_Все`;
- `outgoing_Внешн`;
- `outgoing_Внутр`;
- `internal_Пары`;
- `out_Контрагенты`;
- `out_Поставщики`;
- `unmapped_НеНайдено`;
- `errors_Ошибки`.

В новом проекте добавить листы:

- `accounts_Движение`;
- `accounts_Остатки`;
- `balance_Корректировки`;
- `mapping_Правила`.

## API нового проекта

Примерный набор backend endpoints:

- `POST /api/payment-imports/salesdrive` - запустить импорт за период;
- `GET /api/payment-imports` - история импортов;
- `GET /api/payments` - список платежей с фильтрами;
- `GET /api/payment-reports/summary` - сводка;
- `GET /api/payment-reports/customer-receipts` - входящие клиентские оплаты;
- `GET /api/payment-reports/supplier-payments` - оплаты поставщикам;
- `GET /api/payment-reports/account-movements` - движение по счетам;
- `GET /api/payment-reports/unmapped-counterparties` - unmapped;
- `POST /api/counterparty-mappings` - создать правило;
- `PATCH /api/counterparty-mappings/{id}` - изменить правило;
- `POST /api/payment-reports/recalculate` - пересчитать период после изменения мапинга/корректировок;
- `POST /api/account-balance-adjustments` - внести корректировку;
- `GET /api/payment-reports/export.xlsx` - экспорт текущего отчета в Excel.

## Важные архитектурные решения

1. Не строить отчетность только на Excel.
   Excel должен быть выгрузкой из БД и backend-сервисов.

2. Сохранять raw payload.
   SalesDrive может менять поля, raw JSON позволит восстановить данные.

3. Делать импорт идемпотентным.
   Повторная загрузка того же периода должна обновлять записи, а не плодить дубли.

4. Разделить внутренние переводы и внешние платежи.
   Внутренние переводы нужны для движения по счетам, но не должны искажать клиентские поступления и оплаты поставщикам.

5. Мапинг должен быть управляемым из веба.
   YAML/Excel из старого проекта использовать только как стартовый импорт.

6. Месячные остатки должны иметь ручную корректировку.
   Расчетные остатки могут расходиться с банковскими из-за неполных данных, комиссий или ручных операций.

7. Supplier reconciliation не смешивать с базовым payment reporting.
   В текущем проекте monthly report частично пытается найти файлы сверок поставщиков. В новом проекте базовая платежная отчетность должна работать без файлов сверок.

## План реализации в Inventory_service_1

Этап 1. Инфраструктура данных:

- добавить миграции таблиц;
- добавить модели;
- добавить settings для SalesDrive;
- добавить import run tracking.

Этап 2. Импорт SalesDrive:

- реализовать клиент `/api/payment/list/`;
- загрузка страниц с `limit=100`;
- retry на rate limit/transport errors;
- сохранение raw payload;
- upsert платежей по `source_system + source_payment_id + payment_type`.

Этап 3. Нормализация и классификация:

- перенести правила нормализации;
- классификация incoming;
- детектор внутренних переводов;
- мапинг поставщиков.

Этап 4. Веб-отчеты:

- сводка;
- входящие клиентские;
- исходящие поставщикам;
- движение по счетам;
- unmapped.

Этап 5. Управление мапингом:

- CRUD правил;
- создание правила из unmapped;
- пересчет периода.

Этап 6. Остатки:

- расчет движения по счетам;
- ручные месячные корректировки;
- отчет расхождений.

Этап 7. Excel:

- export текущих веб-отчетов;
- сохранить структуру листов из старого проекта;
- добавить листы движения и корректировок.

## Acceptance criteria

Система считается готовой, если:

- можно импортировать платежи SalesDrive за выбранный период;
- повторный импорт не создает дубли;
- incoming/outcoming отображаются в вебе;
- клиентские входящие отделяются от исключенных и внутренних;
- внутренние переводы определяются по правилам и видны отдельным отчетом;
- исходящие внешние платежи группируются по поставщикам;
- unmapped контрагенты видны и из них можно создать правило мапинга;
- после изменения мапинга можно пересчитать период;
- движение по каждому счету строится за период;
- можно внести месячную корректировку остатка;
- Excel-экспорт содержит те же цифры, что веб;
- отчет работает без файлов supplier reconciliation.

## Стартовый промпт для другого проекта

Ниже текст, который можно дать Codex/другому агенту внутри проекта `Inventory_service_1`.

```text
Нужно реализовать в проекте Inventory_service_1 систему отчетности по платежам на основе документа docs/payment_reporting_transfer_to_inventory_service.md.

Контекст:
- источник платежей: SalesDrive API GET {SALESDRIVE_BASE_URL}/api/payment/list/;
- типы платежей: incoming и outcoming;
- данные надо хранить в БД, а не только формировать Excel;
- веб должен показывать отчеты по периодам;
- Excel должен быть экспортом тех же backend-отчетов;
- supplier reconciliation файлы не нужны для базового payment reporting.

Что нужно сделать:
1. Изучи архитектуру Inventory_service_1: backend framework, ORM, миграции, auth, frontend, существующие отчеты и экспорт Excel.
2. Предложи минимальный план внедрения с учетом существующих паттернов проекта.
3. Реализуй таблицы:
   - payment_import_runs;
   - salesdrive_payments;
   - business_accounts;
   - internal_transfer_pairs;
   - suppliers;
   - counterparty_supplier_mappings;
   - account_balance_adjustments;
   - account_daily_balances или view/materialized view.
4. Реализуй SalesDrive import service:
   - загрузка incoming/outcoming за период;
   - пагинация limit=100;
   - retries;
   - сохранение raw_payload;
   - idempotent upsert.
5. Реализуй нормализацию:
   - source_payment_id = id;
   - payment_date = date;
   - amount = sum;
   - counterparty_name = counterparty.title;
   - counterparty_tax_id = counterparty.egrpou;
   - organization_name = organization.title;
   - organization_tax_id = organization.egrpou;
   - account_reference = organizationAccount.accountNumber;
   - comment и purpose хранить отдельно.
6. Реализуй классификацию incoming:
   - internal_transfer;
   - customer_receipt;
   - excluded_receipt;
   - unknown_incoming как резерв.
7. Реализуй детектор внутренних переводов по правилам:
   - собственные счета и пары счетов из документа;
   - окно пары 5 минут;
   - одинаковая сумма;
   - разные собственные счета;
   - self markers.
8. Реализуй мапинг исходящих платежей на поставщиков:
   - правила exact/contains;
   - priority;
   - active flag;
   - стартовые поставщики DSN, BIOTUS, ZOSIMOV и aliases из документа;
   - unmapped report.
9. Реализуй отчеты в API и вебе:
   - платежи;
   - сводка;
   - входящие клиентские;
   - оплаты поставщикам;
   - движение по счетам;
   - unmapped;
   - импорты.
10. Реализуй месячные корректировки остатков по счетам.
11. Реализуй Excel export:
   - summary_Сводка;
   - receipts_Все;
   - receipts_Клиенты;
   - receipts_Искл;
   - incoming_Все;
   - incoming_Внутр;
   - outgoing_Все;
   - outgoing_Внешн;
   - outgoing_Внутр;
   - internal_Пары;
   - out_Контрагенты;
   - out_Поставщики;
   - unmapped_НеНайдено;
   - errors_Ошибки;
   - accounts_Движение;
   - accounts_Остатки;
   - balance_Корректировки;
   - mapping_Правила.

Важные требования:
- не хранить SalesDrive API key в коде;
- сохранять raw SalesDrive payload;
- импорт должен быть повторяемым без дублей;
- внутренние переводы исключать из клиентских поступлений и оплат поставщикам, но учитывать в движении по счетам;
- мапинг должен редактироваться через веб и применяться пересчетом периода;
- Excel должен экспортировать те же данные, что показывает веб.

Перед изменениями прочитай существующий код проекта и используй его паттерны миграций, сервисов, API, UI и тестов.
```
