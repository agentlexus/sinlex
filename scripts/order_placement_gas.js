/**
 * Google Apps Script — приём заказов Sinlex.
 * Развернуть: Новое развертывание → Веб-приложение → доступ «Все».
 */

var COLUMNS = [
  'Дата', 'Проект', 'Материал', 'Габариты', 'Партия',
  'Цена за ед.', 'Общая стоимость', 'Контакт', 'Телефон', 'Email', 'Комментарий',
];

function doPost(e) {
  try {
    var data = parseBody_(e);
    var row = buildRow_(data);
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(COLUMNS);
    }
    sheet.appendRow(row);
    return json_({ success: true });
  } catch (err) {
    return json_({ success: false, error: String(err) });
  }
}

function doGet() {
  return json_({ success: true, ping: true });
}

function parseBody_(e) {
  if (e && e.postData && e.postData.contents) {
    return JSON.parse(e.postData.contents);
  }
  return (e && e.parameter) ? e.parameter : {};
}

function pick_(data) {
  for (var i = 1; i < arguments.length; i++) {
    var k = arguments[i];
    if (data[k] !== undefined && data[k] !== null && data[k] !== '') {
      return data[k];
    }
  }
  return '';
}

function buildRow_(data) {
  if (data.row && data.row.length) {
    return data.row;
  }
  if (data.values && data.values.length) {
    return data.values;
  }
  if (data.data && data.data.length) {
    return data.data;
  }
  return [
    pick_(data, 'date', 'timestamp', 'Дата'),
    pick_(data, 'project', 'projectName', 'project_name', 'name', 'title', 'nazvanie', 'naimenovanie', 'Название проекта', 'Проект'),
    pick_(data, 'material', 'Материал'),
    pick_(data, 'dimensions', 'gabarites', 'size', 'Габариты'),
    pick_(data, 'quantity', 'batch', 'party', 'qty', 'count', 'Партия'),
    pick_(data, 'unit_price', 'unitPrice', 'pricePerUnit', 'price_item', 'price_unit', 'item_price', 'cost_per_unit', 'cena', 'Цена за ед.', 'Цена'),
    pick_(data, 'total', 'totalPrice', 'total_price', 'total_cost', 'sum', 'stoimost', 'Общая стоимость'),
    pick_(data, 'contact', 'contact_name', 'contactName', 'full_name', 'fio', 'client', 'kontakt', 'Контакт', 'ФИО'),
    pick_(data, 'phone', 'phone_number', 'phoneNumber', 'tel', 'telefon', 'Телефон'),
    pick_(data, 'client_email', 'clientEmail', 'customer_email', 'user_email', 'userEmail', 'email', 'mail', 'E-mail', 'e-mail', 'EMail', 'Email', 'Почта', 'Имейл'),
    pick_(data, 'comment', 'Комментарий'),
  ];
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
