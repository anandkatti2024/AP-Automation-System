import axios from "axios";

const API_URL = "/api/invoices/";

export async function getInvoices() {
  const response = await axios.get(API_URL);
  const data = response.data;
  return Array.isArray(data) ? data : data.results || [];
}

export async function uploadInvoice(file) {
  const formData = new FormData();
  formData.append("invoice_file", file);
  formData.append("invoice_number", `UPLOAD-${Date.now()}`);
  formData.append("vendor_name", "Pending extraction");
  formData.append("currency", "INR");
  formData.append("status", "UPLOADED");

  return axios.post(API_URL, formData);
}

export async function importEmailInvoices(emailFile) {
  const formData = new FormData();
  formData.append("email_file", emailFile);
  const response = await axios.post(`${API_URL}email-import/`, formData);
  return response.data;
}

export async function updateInvoice(invoiceId, updates) {
  const response = await axios.patch(`${API_URL}${invoiceId}/`, updates);
  return response.data;
}

export async function getPurchaseOrders() {
  const response = await axios.get(`${API_URL}purchase-orders/`);
  const data = response.data;
  return Array.isArray(data) ? data : data.results || [];
}

export async function createPurchaseOrder(purchaseOrder) {
  const response = await axios.post(
    `${API_URL}purchase-orders/`,
    purchaseOrder
  );
  return response.data;
}

export async function getGoodsReceipts() {
  const response = await axios.get(`${API_URL}goods-receipts/`);
  const data = response.data;
  return Array.isArray(data) ? data : data.results || [];
}

export async function createGoodsReceipt(goodsReceipt) {
  const response = await axios.post(`${API_URL}goods-receipts/`, goodsReceipt);
  return response.data;
}

export async function submitInvoiceForApproval(invoiceId, comment = "") {
  const response = await axios.post(
    `${API_URL}${invoiceId}/submit-for-approval/`,
    { comment }
  );
  return response.data;
}

export async function approveInvoice(invoiceId, comment = "") {
  const response = await axios.post(`${API_URL}${invoiceId}/approve/`, {
    comment,
  });
  return response.data;
}

export async function rejectInvoice(invoiceId, comment) {
  const response = await axios.post(`${API_URL}${invoiceId}/reject/`, {
    comment,
  });
  return response.data;
}

export async function getInvoicePayments() {
  const response = await axios.get(`${API_URL}payments/`);
  const data = response.data;
  return Array.isArray(data) ? data : data.results || [];
}

export async function getAuditEvents() {
  const response = await axios.get(`${API_URL}audit-events/`, {
    params: { limit: 500 },
  });
  const data = response.data;
  return Array.isArray(data) ? data : data.results || [];
}

export async function getApprovalNotifications() {
  const response = await axios.get(`${API_URL}approval-notifications/`);
  const data = response.data;
  return Array.isArray(data) ? data : data.results || [];
}

export async function markApprovalNotificationRead(notificationId) {
  const response = await axios.post(
    `${API_URL}approval-notifications/${notificationId}/read/`
  );
  return response.data;
}

export async function getPaymentRequests() {
  const response = await axios.get(`${API_URL}payment-requests/`);
  const data = response.data;
  return Array.isArray(data) ? data : data.results || [];
}

export async function createPaymentRequest(invoiceId) {
  const response = await axios.post(`${API_URL}payment-requests/`, {
    invoice: invoiceId,
  });
  return response.data;
}

export async function createStripeConnectTransfer(paymentRequestId) {
  const response = await axios.post(
    `${API_URL}payment-requests/${paymentRequestId}/stripe-transfer/`,
    { confirm: true }
  );
  return response.data;
}

export async function getQuickBooksAuthorizationUrl() {
  const response = await axios.get(
    `${API_URL}integrations/quickbooks/authorize/`
  );
  return response.data.authorization_url;
}

export async function createQuickBooksDraftBill(invoiceId) {
  const response = await axios.post(
    `${API_URL}${invoiceId}/quickbooks-sync/`
  );
  return response.data;
}

export async function createInvoicePayment(invoiceId, payment) {
  const response = await axios.post(
    `${API_URL}${invoiceId}/payments/`,
    payment
  );
  return response.data;
}
