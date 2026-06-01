# Payment API Analysis

## Top-level response fields

- `data`
- `pagination`
- `status`
- `totals`

## Payment item fields

- `comment`
- `counterparty`
- `counterparty.egrpou`
- `counterparty.id`
- `counterparty.title`
- `createdAt`
- `date`
- `documentItems`
- `id`
- `integrationTypeId`
- `nds`
- `organization`
- `organization.egrpou`
- `organization.id`
- `organization.title`
- `organizationAccount`
- `organizationAccount.accountNumber`
- `organizationAccount.id`
- `organizationAccount.title`
- `payerTypeId`
- `paymentBreakdown`
- `purpose`
- `responsibleId`
- `sum`
- `type`
- `updatedAt`
- `userId`

## Interpreted field mapping

- `payment_id` -> `id`
- `payment_date` -> `date`
- `amount` -> `sum`
- `currency` -> unresolved
- `comment` -> `purpose`
- `counterparty_name` -> `counterparty.title`
- `organization_name` -> `organization.title`
- `counterparty_tax_id` -> `organization.egrpou`
- `organization_tax_id` -> `organization.egrpou`
- `account_reference` -> `organizationAccount.accountNumber`
- `raw_status` -> unresolved

## Notes

- Currency field is absent in payment items. Currency may need to be derived from account context or assumed externally.
- Item-level payment status is absent. Top-level response status is only API call status, not payment lifecycle status.
- Some payments may not have a filled counterparty object. In such cases, beneficiary text may only exist in `purpose`.
- `comment` is often empty, while `purpose` contains the business-meaningful payment description. Normalization should prefer `purpose`.

## Example payment payload

```json
{
  "id": 1736,
  "date": "2026-04-30 23:24:31",
  "userId": "",
  "comment": "",
  "sum": "6096.35",
  "purpose": "Переказ коштів по платежам, прийнятим від населення за товари/послуги згідно реєстру № 7576156 від 30.04.2026  та із Заявою №202511033254110820 про приєднання до умов Договору про надання платіжних послуг з переказу коштів (для суб’єктів господарювання) від 03.11.2025р., без/з ПДВ.",
  "nds": 0,
  "payerTypeId": 2,
  "createdAt": "2026-04-30 23:24:46",
  "updatedAt": "2026-04-30 23:24:46",
  "responsibleId": "",
  "type": "incoming",
  "integrationTypeId": 9,
  "documentItems": [],
  "organizationAccount": {
    "id": 2,
    "title": "UA839358710000067321000080261",
    "accountNumber": "UA839358710000067321000080261"
  },
  "organization": {
    "id": 1,
    "egrpou": "3254110820",
    "title": "ФОП Петренко Ірина Анатоліївна"
  },
  "paymentBreakdown": [
    {
      "sum": "6096.35"
    }
  ],
  "counterparty": {
    "id": 6,
    "egrpou": "38324133",
    "title": "НоваПей"
  }
}
```
