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
- `gorod`
- `holderTime`
- `id`
- `numberSup`
- `obrabotano`
- `opt`
- `ord_delivery_data`
- `orderStock`
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
  "id": 12591,
  "formId": 1,
  "version": 8,
  "ord_delivery_data": [
    {
      "senderId": 1,
      "cityName": "Ірпінь",
      "provider": "novaposhta",
      "type": "WarehouseWarehouse",
      "parentTrackingNumber": null,
      "trackingNumber": "20451411660546",
      "isPrinted": 1,
      "statusCode": 9,
      "deliveryDateAndTime": "2026-04-11 12:40:34",
      "idEntity": 1,
      "areaName": "Київська",
      "regionName": "Ірпінська",
      "cityType": "м.",
      "payer": "Recipient",
      "hasPostpay": 1,
      "postpaySum": 483,
      "trackingNumberRef": null,
      "cityRef": "db5c8911-391c-11dd-90d9-001a92567626",
      "settlementRef": "e718466d-4b33-11e4-ab6d-005056801329",
      "branchRef": "aa714e4d-124a-11f1-98dc-8c8474c74af1",
      "branchNumber": 61805,
      "address": "поштомат №61805",
      "paymentMethod": "Cash",
      "postpayPayer": "Recipient",
      "cargoType": "Parcel",
      "addedToRegister": 0
    }
  ],
  "primaryContact": {
    "id": 11353,
    "formId": 1,
    "version": 1,
    "active": 1,
    "lName": "Аліна",
    "fName": "Тістечок",
    "phone": [
      "380993635465"
    ],
    "clientRating": {
      "id": 1171686,
      "phone": "0993635465",
      "buyoutPercent": 100,
      "buyoutLevel": 3,
      "unpicked": 0,
      "canceled": 0,
      "commentPositiveCount": 0,
      "commentNegativeCount": 0,
      "dateUpdated": "2026-04-08 20:23:24"
    },
    "mName": "Костянтинівна",
    "telegram": "",
    "email": [],
    "comment": "",
    "userId": 1,
    "counterpartyId": null,
    "createTime": "2026-04-08 20:23:21",
    "leadsCount": 1,
    "leadsSalesCount": 1,
    "leadsSalesAmount": 483,
    "dateOfBirth": null,
    "company": ""
  },
  "contacts": [
    {
      "id": 11353,
      "formId": 1,
      "version": 1,
      "active": 1,
      "lName": "Аліна",
      "fName": "Тістечок",
      "phone": [
        "380993635465"
      ],
      "clientRating": null,
      "mName": "Костянтинівна",
      "telegram": "",
      "email": [],
      "comment": "",
      "userId": 1,
      "counterpartyId": null,
      "createTime": "2026-04-08 20:23:21",
      "leadsCount": 1,
      "leadsSalesCount": 1,
      "leadsSalesAmount": 483,
      "dateOfBirth": null,
      "company": ""
    }
  ],
  "tabletkiOrder": "587912830",
  "orderTime": "2026-04-08 20:23:20",
  "supplierlist": 39,
  "supplier": "DSN",
  "opt": 412,
  "orderStock": [
    2
  ],
  "numberSup": "",
  "obrabotano": 1,
  "products": [
    {
      "amount": 1,
      "percentCommission": 0,
      "preSale": 0,
      "productId": 95,
      "price": 483,
      "stockId": 2,
      "costPrice": 412,
      "discount": 0,
      "description": "2022-10-2868",
      "commission": 0,
      "percentDiscount": 0,
      "parameter": "1077608",
      "text": "Вітамінно-мінеральний комплекс Nature's Plus Hema-Plex Iron, 30 таблеток повільного вивільнення",
      "barcode": "097467037700",
      "documentName": "Вітамінно-мінеральний комплекс Nature's Plus Hema-Plex Iron, 30 таблеток повільного вивільнення",
      "manufacturer": "Natural Organics Laboratories Inc.",
      "sku": "1077608",
      "uktzed": null
    }
  ],
  "comment": "🟥 Заказ 12591 упал после 2 попытк(и). Последний шаг: add_items. Причина: SET_QTY_FAILED: sku=2022-10-2868, qty=1: SEARCH_NO_RESULTS",
  "qtyOrder": "",
  "qtyOrder_2": "",
  "payment_method": null,
  "rejectionReason": null,
  "shipping_method": 22,
  "shipping_address": "Поштомат \"Нова Пошта\" №61805: вул. Мечнікова, 108А (під'їзд №1)",
  "organizationId": 1,
  "gorod": "",
  "externalId": "9dcbf9e2-14e3-4098-a0dd-c2a77403f82c",
  "utmPage": "",
  "utmMedium": "",
  "campaignId": null,
  "utmSourceFull": "",
  "primecanie": "",
  "statusId": 5,
  "paymentDate": "2026-04-12",
  "paymentAmount": 483,
  "typeId": 1,
  "expensesAmount": 412,
  "profitAmount": 71,
  "city": "Kyiv (Івано-Франківськ)",
  "userId": 1,
  "branch": "59677",
  "commissionAmount": 0,
  "updateAt": "2026-04-12 09:49:16",
  "costPriceAmount": 412,
  "utmSource": "",
  "shipping_costs": null,
  "payedAmount": null,
  "restPay": 483,
  "document_ord_check": null,
  "discountAmount": null,
  "timeEntryOrder": null,
  "call": null,
  "holderTime": null,
  "token": "1ed818a2b2e2f156bce96dfd5f462a53"
}
```
