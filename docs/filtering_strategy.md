# Filtering Strategy

## Входящие платежи

На текущем этапе используется rule-based схема с подтверждением внутренних перемещений парой входящий/исходящий платеж.

Категории:
- `customer_receipt`
- `excluded_receipt`
- `internal_transfer`

Порядок применения правил:

1. По конфигу `config/internal_transfer_rules.yaml` ищется парный внутренний перевод:
   - одинаковая сумма
   - входящий и исходящий
   - разница по времени в пределах окна
   - счета входят в список собственных счетов
   - в тексте есть маркеры self-transfer
2. Если платеж не internal, применяется customer receipt логика из `config/analysis_settings.yaml`
3. Если совпало правило исключения, категория `excluded_receipt`
4. Иначе платеж считается `customer_receipt`

Исключения из customer receipts задаются параметрами:
- `exclude_from_customer_receipts_if_counterparty_contains`
- `exclude_from_customer_receipts_if_comment_contains`
- `exclude_from_customer_receipts_if_exact_counterparty`

На основе марта 2026 в исключения уже добавлены возвраты:
- `повернення`
- `повернення коштів`
- `refund`
- `chargeback`

## Исходящие платежи

Для исходящих платежей пока не делается сложная классификация.
Используется:
- извлечение контрагента
- группировка по нормализованному имени контрагента
- каскадный mapping `counterparty -> supplier`

Порядок supplier mapping:
1. YAML `data/mappings/counterparty_to_supplier.yaml`
2. Excel `data/mappings/counterparty_supplier_mapping.xlsx`
3. если не найдено, запись попадает в `unmapped`

Если supplier не найден:
- запись помечается как `unmapped`
- контрагент попадает в отдельный лист отчета

## Следующий этап развития

- правила на основе реквизитов и счетов
- выделение внутренних переводов не только по строковым паттернам
- приоритеты правил и аудит срабатываний
- связка платежей с заказами и поставщиками
