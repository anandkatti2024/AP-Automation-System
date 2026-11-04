import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import {
  createPaymentRequest,
  createInvoicePayment,
  createStripeConnectTransfer,
  getInvoicePayments,
  getInvoices,
  getPaymentRequests,
} from "../services/invoiceService";
import { formatDate, formatMoney } from "../utils/formatters";

function localDateValue() {
  const today = new Date();
  today.setMinutes(today.getMinutes() - today.getTimezoneOffset());
  return today.toISOString().slice(0, 10);
}

function PaymentManagement({
  invoices,
  onInvoicesChange,
  onMessage,
  onQuickBooksConnect,
  onQuickBooksSync,
  isAdministrator,
}) {
  const [payments, setPayments] = useState([]);
  const [paymentRequests, setPaymentRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedInvoiceId, setSelectedInvoiceId] = useState("");
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    amount: "",
    payment_date: localDateValue(),
    payment_reference: "",
    payment_method: "BANK_TRANSFER",
    notes: "",
  });

  const refreshPayments = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [paymentRecords, invoiceRecords, requestRecords] = await Promise.all([
        getInvoicePayments(),
        getInvoices(),
        getPaymentRequests(),
      ]);
      setPayments(paymentRecords);
      setPaymentRequests(requestRecords);
      onInvoicesChange(invoiceRecords);
    } catch (requestError) {
      setError(
        requestError.response
          ? `Could not load payment data (HTTP ${requestError.response.status}).`
          : "Could not connect to the Django API."
      );
    } finally {
      setLoading(false);
    }
  }, [onInvoicesChange]);

  useEffect(() => {
    let isCurrent = true;
    Promise.all([getInvoicePayments(), getInvoices(), getPaymentRequests()])
      .then(([paymentRecords, invoiceRecords, requestRecords]) => {
        if (!isCurrent) return;
        setPayments(paymentRecords);
        setPaymentRequests(requestRecords);
        onInvoicesChange(invoiceRecords);
      })
      .catch((requestError) => {
        if (!isCurrent) return;
        setError(
          requestError.response
            ? `Could not load payment data (HTTP ${requestError.response.status}).`
            : "Could not connect to the Django API."
        );
      })
      .finally(() => {
        if (isCurrent) setLoading(false);
      });

    return () => {
      isCurrent = false;
    };
  }, [onInvoicesChange]);

  const approvedInvoices = invoices.filter(
    (invoice) => invoice.status === "APPROVED"
  );

  function getPaidAmount(invoiceId) {
    const paidInCents = payments
      .filter((payment) => payment.invoice === invoiceId)
      .reduce((total, payment) => total + Math.round(Number(payment.amount) * 100), 0);
    return paidInCents / 100;
  }

  function startPayment(invoice) {
    const remaining = Number(invoice.total_amount) - getPaidAmount(invoice.id);
    setSelectedInvoiceId(String(invoice.id));
    setForm({
      amount: remaining.toFixed(2),
      payment_date: localDateValue(),
      payment_reference: "",
      payment_method: "BANK_TRANSFER",
      notes: "",
    });
    setError("");
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const invoice = approvedInvoices.find(
      (record) => String(record.id) === selectedInvoiceId
    );
    if (!invoice) return;

    setSaving(true);
    setError("");
    try {
      await createInvoicePayment(invoice.id, form);
      setSelectedInvoiceId("");
      await refreshPayments();
      onMessage(`Payment recorded for invoice ${invoice.invoice_number}.`);
    } catch (requestError) {
      setError(
        requestError.response?.data
          ? `Could not record payment: ${JSON.stringify(requestError.response.data)}`
          : "Could not record payment. Check the Django API."
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleCreatePaymentRequest(invoice) {
    setError("");
    try {
      const paymentRequest = await createPaymentRequest(invoice.id);
      setPaymentRequests((current) => [paymentRequest, ...current]);
      onMessage(
        `Payment request created for ${invoice.invoice_number}; no bank transfer was initiated.`
      );
    } catch (requestError) {
      setError(
        requestError.response?.data
          ? `Could not create payment request: ${JSON.stringify(requestError.response.data)}`
          : "Could not create payment request. Check the Django API."
      );
    }
  }

  async function handleStripeTransfer(paymentRequest) {
    const confirmed = window.confirm(
      `Send ${formatMoney(paymentRequest.requested_amount, paymentRequest.currency)} ` +
      `for invoice ${paymentRequest.invoice_number} to ${paymentRequest.vendor_name}'s ` +
      "Stripe Connect account? This initiates a live transfer and may not be reversible."
    );
    if (!confirmed) return;

    setSaving(true);
    setError("");
    try {
      await createStripeConnectTransfer(paymentRequest.id);
      await refreshPayments();
      onMessage(
        `Stripe Connect transfer submitted for invoice ${paymentRequest.invoice_number}.`
      );
    } catch (requestError) {
      setError(
        requestError.response?.data
          ? `Stripe transfer failed: ${JSON.stringify(requestError.response.data)}`
          : "Stripe transfer failed. Check the Django API."
      );
    } finally {
      setSaving(false);
    }
  }

  function printPaymentAdvice(payment) {
    const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[char]);
    const adviceWindow = window.open("", "_blank");
    if (!adviceWindow) {
      setError("Allow pop-ups to generate the printable payment advice.");
      return;
    }
    adviceWindow.document.write(`
      <!doctype html>
      <html lang="en">
        <head>
          <meta charset="utf-8">
          <title>Payment advice ${escapeHtml(payment.payment_reference)}</title>
          <style>
            body { max-width: 720px; margin: 48px auto; padding: 24px; color: #233247; font: 14px Arial, sans-serif; }
            h1 { margin-bottom: 4px; } .muted { color: #69788c; }
            table { width: 100%; margin-top: 24px; border-collapse: collapse; }
            th, td { padding: 12px; border: 1px solid #dfe5ee; text-align: left; }
            th { width: 34%; background: #f5f7fa; }
            .amount { font-size: 19px; font-weight: bold; }
            @media print { body { margin: 0; } }
          </style>
        </head>
        <body>
          <h1>Payment advice</h1>
          <p class="muted">Templegate Accounts Payable</p>
          <table>
            <tr><th>Vendor</th><td>${escapeHtml(payment.vendor_name)}</td></tr>
            <tr><th>Invoice</th><td>${escapeHtml(payment.invoice_number)}</td></tr>
            <tr><th>Payment date</th><td>${escapeHtml(formatDate(payment.payment_date))}</td></tr>
            <tr><th>Payment reference</th><td>${escapeHtml(payment.payment_reference)}</td></tr>
            <tr><th>Payment method</th><td>${escapeHtml(payment.payment_method.replaceAll("_", " "))}</td></tr>
            <tr><th>Amount</th><td class="amount">${escapeHtml(formatMoney(payment.amount, payment.currency))}</td></tr>
            <tr><th>Notes</th><td>${escapeHtml(payment.notes || "—")}</td></tr>
          </table>
          <p class="muted">This advice confirms a payment record in the AP system. It is not proof of a bank transfer.</p>
          <script>window.onload = () => window.print();</script>
        </body>
      </html>
    `);
    adviceWindow.document.close();
  }

  const selectedInvoice = approvedInvoices.find(
    (invoice) => String(invoice.id) === selectedInvoiceId
  );

  return (
    <section className="payment-page">
      <div className="payment-page-heading">
        <div>
          <div className="eyebrow">ACCOUNTS PAYABLE</div>
          <h1>Payment processing</h1>
          <p>Record payments against approved invoices and track outstanding balances.</p>
        </div>
        <button
          className="button secondary"
          type="button"
          onClick={refreshPayments}
          disabled={loading}
        >
          <RefreshCw size={16} /> Refresh
        </button>
      </div>

      <div className="payment-guidance">
        Stripe Connect transfers are initiated only after explicit confirmation.
        Manual payment records remain available. A successful transfer is recorded
        against the invoice; invoices are marked Paid when the full amount is covered.
        The transfer itself does not confirm the connected account's bank payout.
      </div>
      {isAdministrator && (
        <div className="vendor-list-panel">
          <div className="vendor-list-heading">
            <div>
              <h2>QuickBooks Online</h2>
              <p>Connect QuickBooks to create pending bills for approved invoices.</p>
            </div>
            <button
              className="button secondary"
              type="button"
              onClick={onQuickBooksConnect}
            >
              Connect QuickBooks
            </button>
          </div>
        </div>
      )}
      {error && <div className="vendor-error" role="alert">{error}</div>}

      {selectedInvoice && (
        <form className="vendor-form-panel" onSubmit={handleSubmit}>
          <div className="vendor-form-heading">
            <div>
              <h2>Record payment for {selectedInvoice.invoice_number}</h2>
              <p>
                Outstanding:{" "}
                {formatMoney(
                  Number(selectedInvoice.total_amount) -
                    getPaidAmount(selectedInvoice.id),
                  selectedInvoice.currency
                )}
              </p>
            </div>
          </div>
          <div className="vendor-form-fields">
            <label className="review-field">
              <span>Payment amount *</span>
              <input
                type="number"
                min="0.01"
                max={(
                  Number(selectedInvoice.total_amount) -
                  getPaidAmount(selectedInvoice.id)
                ).toFixed(2)}
                step="0.01"
                value={form.amount}
                onChange={(event) =>
                  setForm((current) => ({ ...current, amount: event.target.value }))
                }
                required
              />
            </label>
            <label className="review-field">
              <span>Payment date *</span>
              <input
                type="date"
                value={form.payment_date}
                max={localDateValue()}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    payment_date: event.target.value,
                  }))
                }
                required
              />
            </label>
            <label className="review-field">
              <span>Payment reference *</span>
              <input
                value={form.payment_reference}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    payment_reference: event.target.value,
                  }))
                }
                maxLength={100}
                required
              />
            </label>
            <label className="review-field">
              <span>Payment method *</span>
              <select
                value={form.payment_method}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    payment_method: event.target.value,
                  }))
                }
              >
                <option value="BANK_TRANSFER">Bank transfer</option>
                <option value="CHEQUE">Cheque</option>
                <option value="UPI">UPI</option>
                <option value="OTHER">Other</option>
              </select>
            </label>
            <label className="review-field payment-notes-field">
              <span>Notes</span>
              <textarea
                rows={3}
                value={form.notes}
                onChange={(event) =>
                  setForm((current) => ({ ...current, notes: event.target.value }))
                }
              />
            </label>
          </div>
          <div className="vendor-form-actions">
            <button
              className="button secondary"
              type="button"
              onClick={() => setSelectedInvoiceId("")}
              disabled={saving}
            >
              Cancel
            </button>
            <button className="button primary" type="submit" disabled={saving}>
              {saving ? "Recording..." : "Record payment"}
            </button>
          </div>
        </form>
      )}

      <section className="vendor-list-panel">
        <div className="vendor-list-heading">
          <div>
            <h2>Approved invoices</h2>
            <p>{approvedInvoices.length} invoice{approvedInvoices.length === 1 ? "" : "s"} available for payment</p>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>INVOICE</th><th>VENDOR</th><th>DUE DATE</th>
                <th>INVOICE TOTAL</th><th>PAID</th><th>OUTSTANDING</th><th>ACTIONS</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan="7" className="empty-state">Loading payment data...</td></tr>
              ) : approvedInvoices.length === 0 ? (
                <tr><td colSpan="7" className="empty-state">No approved invoices are awaiting payment.</td></tr>
              ) : approvedInvoices.map((invoice) => {
                const paid = getPaidAmount(invoice.id);
                const outstanding = Number(invoice.total_amount) - paid;
                return (
                  <tr key={invoice.id}>
                    <td><span className="invoice-id">{invoice.invoice_number}</span></td>
                    <td>{invoice.vendor_name}</td>
                    <td>{formatDate(invoice.due_date)}</td>
                    <td className="amount">{formatMoney(invoice.total_amount, invoice.currency)}</td>
                    <td className="amount">{formatMoney(paid, invoice.currency)}</td>
                    <td className="amount">{formatMoney(outstanding, invoice.currency)}</td>
                    <td>
                      {invoice.quickbooks_bill_id ? (
                        <span className="invoice-id">
                          QBO bill {invoice.quickbooks_bill_id}
                        </span>
                      ) : (
                        <button
                          className="vendor-edit-button"
                          type="button"
                          disabled={!onQuickBooksSync}
                          onClick={() => onQuickBooksSync(invoice.id)}
                        >
                          Create QBO draft
                        </button>
                      )}
                      <button
                        className="vendor-edit-button"
                        type="button"
                        disabled={
                          outstanding <= 0 ||
                          paymentRequests.some(
                            (item) =>
                              item.invoice === invoice.id &&
                              item.status === "REQUESTED"
                          )
                        }
                        onClick={() => handleCreatePaymentRequest(invoice)}
                      >
                        {paymentRequests.some(
                          (item) =>
                            item.invoice === invoice.id &&
                            item.status === "REQUESTED"
                        )
                          ? "Requested"
                          : "Request payment"}
                      </button>
                      <button
                        className="vendor-edit-button"
                        type="button"
                        disabled={outstanding <= 0}
                        onClick={() => startPayment(invoice)}
                      >
                        Record payment
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="vendor-list-panel">
        <div className="vendor-list-heading">
          <div>
            <h2>Payment requests</h2>
            <p>{paymentRequests.length} payment request{paymentRequests.length === 1 ? "" : "s"} recorded.</p>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>INVOICE</th><th>VENDOR</th><th>AMOUNT</th><th>STATUS</th><th>REQUESTED BY</th><th>DATE</th><th>ACTION</th></tr>
            </thead>
            <tbody>
              {paymentRequests.length === 0 ? (
                <tr><td colSpan="7" className="empty-state">No payment requests have been generated.</td></tr>
              ) : paymentRequests.map((item) => (
                <tr key={item.id}>
                  <td><span className="invoice-id">{item.invoice_number}</span></td>
                  <td>{item.vendor_name}</td>
                  <td className="amount">{formatMoney(item.requested_amount, item.currency)}</td>
                  <td>{item.status.replaceAll("_", " ")}</td>
                  <td>{item.requested_by_name}</td>
                  <td>{formatDate(item.created_at)}</td>
                  <td>
                    {item.status === "REQUESTED" && (
                      <button
                        className="vendor-edit-button"
                        type="button"
                        disabled={saving}
                        onClick={() => handleStripeTransfer(item)}
                      >
                        Pay via Stripe
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="vendor-list-panel">
        <div className="vendor-list-heading">
          <div>
            <h2>Payment history</h2>
            <p>{payments.length} payment{payments.length === 1 ? "" : "s"} recorded</p>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>PAYMENT DATE</th><th>INVOICE</th><th>VENDOR</th>
                <th>METHOD</th><th>REFERENCE</th><th>AMOUNT</th><th>RECORDED BY</th><th></th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan="8" className="empty-state">Loading payment history...</td></tr>
              ) : payments.length === 0 ? (
                <tr><td colSpan="8" className="empty-state">No payments have been recorded.</td></tr>
              ) : payments.map((payment) => (
                <tr key={payment.id}>
                  <td>{formatDate(payment.payment_date)}</td>
                  <td><span className="invoice-id">{payment.invoice_number}</span></td>
                  <td>{payment.vendor_name}</td>
                  <td>{payment.payment_method.replaceAll("_", " ")}</td>
                  <td>{payment.payment_reference}</td>
                  <td className="amount">{formatMoney(payment.amount, payment.currency)}</td>
                  <td>{payment.actor_name}</td>
                  <td>
                    <button
                      className="vendor-edit-button"
                      type="button"
                      onClick={() => printPaymentAdvice(payment)}
                    >
                      Payment advice
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}

export default PaymentManagement;
