# Order API Analysis

## Top-level response fields

- `data`
- `meta`
- `pagination`
- `status`
- `totals`

## Order item fields

- `branch`
- `call`
- `campaignId`
- `city`
- `comment`
- `commissionAmount`
- `contacts`
- `costPriceAmount`
- `discountAmount`
- `document_ord_check`
- `expensesAmount`
- `externalId`
- `formId`
- `holderTime`
- `id`
- `numberSup`
- `obrabotano`
- `opt`
- `ord_delivery_data`
- `orderTime`
- `organizationId`
- `payedAmount`
- `paymentAmount`
- `paymentDate`
- `payment_method`
- `primaryContact`
- `primecanie`
- `products`
- `profitAmount`
- `qtyOrder`
- `qtyOrder_2`
- `rejectionReason`
- `restPay`
- `shipping_address`
- `shipping_costs`
- `shipping_method`
- `statusId`
- `supplier`
- `supplierlist`
- `tabletkiOrder`
- `timeEntryOrder`
- `token`
- `typeId`
- `updateAt`
- `userId`
- `utmMedium`
- `utmPage`
- `utmSource`
- `utmSourceFull`
- `version`

## Confirmed reconciliation fields

- `supplierlist`: present
- `numberSup`: present
- `expensesAmount`: present
- `paymentAmount`: present
- `statusId`: present
- `orderTime`: present
- `updateAt`: present
- `id`: present

## Notes

- SalesDrive order API uses `updateAt` in the live payload, not `updatedAt`.
- Live Biotus orders expose `numberSup` values with `BO-...` prefix, while supplier reconciliation uses `BI-...`.
- Reconciliation layer normalizes supplier document keys by numeric suffix, so `BO-00046907` and `BI-00046907` are treated as the same supplier reference for matching.

## Example order payload

```json
{
  "id": 11622,
  "formId": 1,
  "version": 2,
  "ord_delivery_data": [
    {
      "provider": "novaposhta",
      "senderId": 1,
      "type": "WarehouseWarehouse",
      "trackingNumber": null,
      "parentTrackingNumber": null,
      "cityName": "Чернівці",
      "statusCode": null,
      "deliveryDateAndTime": null,
      "isPrinted": 0,
      "idEntity": 1,
      "areaName": "Чернівецька",
      "regionName": "",
      "cityType": "м.",
      "payer": "Recipient",
      "hasPostpay": 1,
      "postpaySum": 506.5,
      "trackingNumberRef": null,
      "cityRef": "e221d642-391c-11dd-90d9-001a92567626",
      "settlementRef": "e71fe717-4b33-11e4-ab6d-005056801329",
      "branchRef": "a35e0dc0-5edf-11ef-98f8-d4f5ef0df2b9",
      "branchNumber": 43950,
      "address": "поштомат №43950",
      "addedToRegister": 0
    }
  ],
  "primaryContact": {
    "id": 10502,
    "formId": 1,
    "version": 1,
    "active": 1,
    "lName": "Гордей",
    "fName": "Олександр",
    "phone": [
      "380964716194"
    ],
    "clientRating": {
      "id": 4662249,
      "phone": "0964716194",
      "buyoutPercent": null,
      "buyoutLevel": null,
      "unpicked": null,
      "canceled": null,
      "commentPositiveCount": null,
      "commentNegativeCount": null,
      "dateUpdated": "2026-04-01 18:24:07"
    },
    "mName": "Олександрович",
    "telegram": "",
    "email": [],
    "comment": "",
    "userId": 1,
    "counterpartyId": null,
    "createTime": "2026-04-01 18:24:06",
    "leadsCount": 1,
    "leadsSalesCount": 0,
    "leadsSalesAmount": 0,
    "dateOfBirth": null,
    "company": ""
  },
  "contacts": [
    {
      "id": 10502,
      "formId": 1,
      "version": 1,
      "active": 1,
      "lName": "Гордей",
      "fName": "Олександр",
      "phone": [
        "380964716194"
      ],
      "clientRating": null,
      "mName": "Олександрович",
      "telegram": "",
      "email": [],
      "comment": "",
      "userId": 1,
      "counterpartyId": null,
      "createTime": "2026-04-01 18:24:06",
      "leadsCount": 1,
      "leadsSalesCount": 0,
      "leadsSalesAmount": 0,
      "dateOfBirth": null,
      "company": ""
    }
  ],
  "tabletkiOrder": "849917189",
  "orderTime": "2026-04-01 18:24:06",
  "supplierlist": 41,
  "supplier": "DOBAVKI.UA",
  "opt": 442,
  "numberSup": "",
  "obrabotano": null,
  "products": [
    {
      "amount": 1,
      "percentCommission": 0,
      "preSale": 0,
      "productId": 829,
      "price": 506.5,
      "stockId": 2,
      "costPrice": 442,
      "discount": 0,
      "description": "NAP-29942",
      "commission": 0,
      "percentDiscount": 0,
      "parameter": "1063154",
      "text": "Магній для дітей Nature's Plus Animal Parade Children's Magnesium без цукру, вишня, 90 таблеток",
      "barcode": "097467299429",
      "documentName": "Магній для дітей Nature's Plus Animal Parade Children's Magnesium без цукру, вишня, 90 таблеток",
      "manufacturer": "Natural Organics Laboratories Inc.",
      "sku": "1063154",
      "uktzed": null
    }
  ],
  "comment": "",
  "qtyOrder": "",
  "qtyOrder_2": "",
  "payment_method": null,
  "rejectionReason": null,
  "shipping_method": 22,
  "shipping_address": "Поштомат \"Нова Пошта\" №43950: вул. Комунальників, 7в (\"DigitalCARservice\")",
  "organizationId": 1,
  "externalId": "17856b9c-ab95-4b37-b777-c0fb389389a3",
  "utmPage": "",
  "utmMedium": "",
  "campaignId": null,
  "utmSourceFull": "",
  "primecanie": "",
  "statusId": 6,
  "paymentDate": null,
  "paymentAmount": 506.5,
  "typeId": 1,
  "expensesAmount": 442,
  "profitAmount": 64.5,
  "city": "Kyiv (Львів)",
  "userId": 1,
  "branch": "59677",
  "commissionAmount": 0,
  "updateAt": "2026-04-01 18:25:12",
  "costPriceAmount": 442,
  "utmSource": "",
  "shipping_costs": null,
  "payedAmount": null,
  "restPay": 506.5,
  "document_ord_check": null,
  "discountAmount": null,
  "timeEntryOrder": null,
  "call": null,
  "holderTime": null,
  "token": "07332a44c9c3d8437eee20d919bb2677"
}
```
