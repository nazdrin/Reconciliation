# Project Status And Configuration

## Scope

Проект `payment_analysis` состоит из двух основных слоев:

1. `stage 1 payment pipeline`
   - загрузка входящих и исходящих платежей из SalesDrive
   - пагинация
   - нормализация
   - internal transfer detection
   - supplier mapping
   - monthly Excel reports

2. `supplier reconciliation layer`
   - provider-specific parsing supplier files
   - order reconciliation against SalesDrive
   - payment reconciliation там, где это применимо
   - return reconciliation там, где это применимо
   - supplier-specific Excel reports

## Current Providers

На текущий момент реализованы следующие reconciliation providers:

- `biotus`
  - supplier code: `38`
  - source files: `supplier_reconciliation/biotus/`
  - логика:
    - payment reconciliation
    - order reconciliation
    - return reconciliation
    - deposit opening/closing balances

- `monsterlab`
  - supplier code: `42`
  - source files: `supplier_reconciliation/monsterlab/`
  - логика:
    - PDF parsing
    - payment reconciliation
    - order reconciliation partial
    - deposit balances

- `Sport-atlet`
  - supplier code: `43`
  - source files: `supplier_reconciliation/Sport-atlet/`
  - логика:
    - orders and returns from `Приход`
    - payments from `Расход`
    - negative deposit balances normalized to abs values

- `dsn`
  - supplier code: `39`
  - source files: `supplier_reconciliation/dsn/`
  - логика:
    - payment reconciliation
    - order reconciliation
    - return reconciliation
    - normalized document number matching with leading-zero fallback

- `proteinplus`
  - supplier code: `40`
  - source files: `supplier_reconciliation/ProteinPlus/`
  - логика:
    - no payment reconciliation
    - separate deposit file and orders file
    - order reconciliation by `trackingNumber`
    - returns from deposit movements
    - automatic USD -> UAH conversion via NBU rate on period end date

- `Dobavki.ua`
  - supplier code: `41`
  - source files: `supplier_reconciliation/dobavki_ua/`
  - логика:
    - no payment reconciliation
    - single xls file
    - order reconciliation by `trackingNumber`
    - supplier file mapping:
      - `Виконано` -> SalesDrive `statusId = 5`
      - `Повернення` -> SalesDrive `statusId = 7`
    - period filter for reconciliation uses `orderTime`

## Key Configuration Files

- `config/analysis_settings.yaml`
  - default monthly period for stage 1 reports

- `config/internal_transfer_rules.yaml`
  - own account / self-transfer detection rules

- `config/incoming_rules.yaml`
  - incoming payment classification rules

- `config/supplier_reconciliation.yaml`
  - provider-specific reconciliation configuration:
    - supplier code
    - folder
    - matching strategy
    - date tolerances
    - allowed sale statuses
    - provider-specific file patterns
    - ProteinPlus FX settings

- `data/mappings/counterparty_to_supplier.yaml`
  - YAML supplier aliases

- `data/mappings/counterparty_supplier_mapping.xlsx`
  - Excel source of truth for `supplier_name` labels in payment reports

## Environment Variables

Required:

- `SALESDRIVE_BASE_URL`
- `SALESDRIVE_API_KEY`
- `SALESDRIVE_ORDER_API_KEY`

Optional:

- `SALESDRIVE_TIMEOUT_SECONDS`
- `SALESDRIVE_PAGE_LIMIT`
- `SALESDRIVE_RATE_LIMIT_RETRY_SECONDS`
- `SALESDRIVE_RATE_LIMIT_MAX_RETRIES`

## Outputs

Main monthly payment reports:

- `reports/payment_report_YYYY_MM.xlsx`

Supplier reconciliation reports:

- `reports/biotus_reconciliation_YYYY_MM.xlsx`
- `reports/monsterlab_reconciliation_YYYY_MM.xlsx`
- `reports/sport_atlet_reconciliation_YYYY_MM.xlsx`
- `reports/dsn_reconciliation_YYYY_MM.xlsx`
- `reports/proteinplus_reconciliation_YYYY_MM.xlsx`
- `reports/dobavki_ua_reconciliation_YYYY_MM.xlsx`

## Current Rules Worth Calling Out

- `ProteinPlus`
  - order key: `supplier file Номер ТТН` -> `SalesDrive trackingNumber`
  - amount field in SalesDrive: `paymentAmount`
  - order filter in reconciliation: `statusId = 5`, period by `updateAt`
  - returns are financial movements from deposit file

- `Dobavki.ua`
  - order key: `Коментар` -> `trackingNumber`
  - amount field in SalesDrive: `expensesAmount`
  - order filter in reconciliation: `statusId = 5`, period by `orderTime`
  - return filter in reconciliation: `statusId = 7`, period by `orderTime`

## Current Limitations

- Некоторые providers still require provider-specific amount interpretation in SalesDrive.
- `ProteinPlus` amount reconciliation is still sensitive to how supplier COD amount maps to SalesDrive financial fields.
- `MonsterLab` order key mapping still needs deeper SalesDrive schema audit if full match quality becomes required.

## Recommended Next Steps

1. Зафиксировать rounding/formatting policy for monetary values in summary sheets.
2. Добавить provider-specific docs for `ProteinPlus`, `Dobavki.ua`, and `MonsterLab`.
3. Вынести explicit report metadata:
   - fetch window
   - period filter field (`orderTime` vs `updateAt`)
   - amount field used for reconciliation
4. Добавить lightweight regression tests for provider parsers and matching rules.
