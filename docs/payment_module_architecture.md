# Payment Module Architecture

## Цель этапа

Собрать расширяемый модуль для:
- загрузки входящих и исходящих платежей из SalesDrive
- нормализации в единую внутреннюю модель
- первичной классификации входящих
- группировки исходящих по контрагентам и поставщикам
- выгрузки отчетов в Excel

## Модули

### `config.py`
- загрузка `.env`
- валидация обязательных настроек
- пути к debug, mappings, rules, docs, reports

### `clients/salesdrive_client.py`
- HTTP-клиент для `GET /api/payment/list/`
- загрузка одной страницы
- загрузка всех страниц
- таймауты, обработка HTTP-ошибок, логирование
- сохранение первого raw response в `debug/`

### `services/payment_loader.py`
- orchestration для `incoming`, `outcoming`, `all`
- объединение результатов нескольких вызовов API

### `services/payment_normalizer.py`
- извлечение ключевых полей из сырого платежа
- преобразование в `PaymentRecord`
- анализ структуры ответа и генерация markdown-документации

### `services/payment_filters.py`
- загрузка правил customer receipts
- исключения из клиентских поступлений
- классификация входящих платежей

### `services/payment_mapper.py`
- загрузка mapping-файла поставщиков
- fallback на Excel mapping
- маппинг контрагента на supplier
- список unmapped-контрагентов

### `services/internal_transfer_detector.py`
- загрузка правил собственных счетов
- поиск пар входящий/исходящий платеж
- маркировка внутренних переводов

### `reports/excel_report.py`
- построение Excel workbook
- отдельные листы для сырых и агрегированных данных

### `services/payment_analysis_service.py`
- основной pipeline
- связывает загрузку, нормализацию, классификацию, маппинг и отчет

## Основные сущности

### `PaymentRecord`
- `payment_id`
- `payment_type`
- `payment_date`
- `amount`
- `currency`
- `counterparty_name`
- `counterparty_tax_id`
- `comment`
- `purpose`
- `organization_name`
- `organization_tax_id`
- `account_reference`
- `raw_status`
- `supplier_name`
- `incoming_category`
- `is_internal_transfer`
- `internal_transfer_pair_id`
- `internal_transfer_reason`
- `source_system`
- `raw_payload`

### `PaymentPage`
- `items`
- `page`
- `limit`
- `total_items`
- `total_pages`
- `raw_response`

### `PaymentAnalysisResult`
- список входящих
- список исходящих
- агрегаты по контрагентам
- агрегаты по поставщикам
- unmapped-контрагенты
- ошибки

## Принципы расширения

- API-слой не знает про классификацию и поставщиков.
- Нормализация не знает про Excel.
- Правила фильтрации вынесены в YAML, а supplier mapping во внешний файл.
- Полный raw payload сохраняется в каждой записи, чтобы позже добавлять:
  - сверку с файлами поставщиков
  - маппинг к заказам
  - дополнительные правила и эвристики

## Наблюдения По Живому API

- Ответ API имеет стабильную верхнюю обертку:
  - `data`
  - `pagination`
  - `totals`
  - `status`
- Полезные бизнес-поля платежа находятся внутри вложенных объектов:
  - `counterparty.title`
  - `counterparty.egrpou`
  - `organization.title`
  - `organization.egrpou`
  - `organizationAccount.accountNumber`
- Основное описание платежа практически значимо в `purpose`, а не в `comment`.
- Поля `currency` и item-level `status` в payload не обнаружены.
- У части исходящих платежей контрагент не заполнен отдельным объектом и читается только из текста `purpose`.

## Предложение Для Следующего Этапа

### 1. Усилить внутреннюю модель

Добавить во внутреннюю нормализованную модель:
- `counterparty_tax_id`
- `organization_tax_id`
- `organization_account_number`
- `integration_type_id`
- `payer_type_id`
- `purpose`
- `comment_raw`

Причина:
- эти поля реально приходят из API и полезны для сверки, supplier matching и последующего связывания с заказами.

### 2. Вынести парсинг назначения платежа

Добавить модуль:
- `services/payment_text_parser.py`

Задачи:
- извлечение номера заказа
- извлечение номера счета
- извлечение признака внутреннего перевода
- fallback-извлечение контрагента, если `counterparty` пустой

### 3. Ввести audit trail для правил

Добавить отдельную модель результата классификации:
- `category`
- `matched_rule_type`
- `matched_rule_value`
- `explanation`

Причина:
- на живых данных уже видно, что правила начинают играть ключевую роль, особенно для `НоваПей` и внутренних переводов.

### 4. Подготовить слой reference data

Добавить каталог:
- `data/reference/`

И загрузчики:
- `supplier_mapping`
- `internal_entities`
- `payment_channels`

Причина:
- live payload показывает, что часть логики будет строиться не только на names, но и на ЕГРПОУ, счетах и типах интеграции.
