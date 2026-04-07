# Supplier Reconciliation Architecture

## Goal

Расширение stage 1 payment pipeline слоем supplier reconciliation без переписывания существующей логики.

## Layers

- `clients/salesdrive_client.py`
  Платежи и заказы SalesDrive API.
- `services/*`
  Stage 1 pipeline остается как есть.
- `reconciliation/*`
  Новый orchestration слой для актов сверки поставщиков.
- `reports/excel_report.py`
  Дополнен отдельным builder-методом для reconciliation workbook.

## Flow

1. Найти файл сверки поставщика по периоду.
2. Распарсить supplier-specific file parser.
3. Переиспользовать stage 1 payment loading и mapping для исходящих платежей.
4. Загрузить orders из SalesDrive.
5. Выполнить payment reconciliation.
6. Выполнить order reconciliation.
7. Связать returns с orders по `numberSup`.
8. Собрать supplier-specific Excel report.

## Extensibility

- Новый поставщик добавляется через:
  - `config/supplier_reconciliation.yaml`
  - новый parser в `reconciliation/providers/`
  - при необходимости provider-specific matching rules
