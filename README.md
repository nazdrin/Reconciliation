# Payment Analysis

Первый этап анализа платежей из SalesDrive API.

Дополнительно проект уже включает `supplier reconciliation layer` для сверки заказов, возвратов, оплат и provider-specific supplier files.

## Быстрый старт

1. Создать виртуальное окружение и установить зависимости:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

2. Заполнить `.env` на основе `.env.example`.

3. При необходимости скорректировать конфиги:

- `config/analysis_settings.yaml`
- `config/internal_transfer_rules.yaml`
- `data/mappings/counterparty_to_supplier.yaml`
- `data/mappings/counterparty_supplier_mapping.xlsx`

4. Запустить анализ за месяц:

```bash
python -m scripts.run_payment_analysis \
  --type all \
  --month 2026-03
```

Явный вывод в отдельный файл:

```bash
python -m scripts.run_payment_analysis \
  --type all \
  --month 2026-03 \
  --output reports/payment_report_2026_03.xlsx
```

После первого успешного запроса:
- raw JSON будет сохранен в `debug/`
- анализ структуры ответа будет обновлен в `docs/payment_api_analysis.md`
- Excel-отчет будет создан в `reports/`

## Supplier Reconciliation

Для supplier reconciliation используется отдельный entrypoint, не затрагивающий stage 1 monthly payment report:

```bash
python -m scripts.run_supplier_reconciliation \
  --supplier biotus \
  --period 2026-02 \
  --output reports/biotus_reconciliation_2026_02.xlsx
```

Примеры по месяцам:

```bash
python -m scripts.run_supplier_reconciliation \
  --supplier biotus \
  --period 2026-03 \
  --output reports/biotus_reconciliation_2026_03.xlsx
```

```bash
python -m scripts.run_supplier_reconciliation \
  --supplier dsn \
  --period 2026-03 \
  --output reports/dsn_reconciliation_2026_03.xlsx
```

```bash
python -m scripts.run_supplier_reconciliation \
  --supplier "Sport-atlet" \
  --period 2026-03 \
  --output reports/sport_atlet_reconciliation_2026_03.xlsx
```

```bash
python -m scripts.run_supplier_reconciliation \
  --supplier proteinplus \
  --period 2026-03 \
  --output reports/proteinplus_reconciliation_2026_03.xlsx
```

```bash
python -m scripts.run_supplier_reconciliation \
  --supplier "Dobavki.ua" \
  --period 2026-03 \
  --output reports/dobavki_ua_reconciliation_2026_03.xlsx
```

При первом успешном запуске:
- raw order API response будет сохранен в `debug/`
- audit структуры order API будет обновлен в `docs/order_api_analysis.md`
- supplier-specific reconciliation report будет создан в `reports/`

## Documentation

Ключевые документы проекта:

- `docs/payment_module_architecture.md`
- `docs/payment_api_analysis.md`
- `docs/filtering_strategy.md`
- `docs/supplier_reconciliation_architecture.md`
- `docs/order_api_analysis.md`
- `docs/stage1_work_summary.md`
- `docs/project_status_and_configuration.md`
