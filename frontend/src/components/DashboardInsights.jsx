import { useEffect, useMemo, useState } from "react";
import { Banknote, CalendarClock, UsersRound } from "lucide-react";
import { getInvoicePayments } from "../services/invoiceService";
import { formatDate, formatMoney } from "../utils/formatters";
import {
  buildAgingSummary,
  buildPaymentTracking,
  buildVendorSummary,
  paidAmountByInvoice,
} from "../utils/dashboardAnalytics";

function MoneyList({ totals }) {
  if (!totals?.length) return <strong>—</strong>;
  return (
    <div className="dashboard-money-list">
      {totals.map(({ currency, amount }) => (
        <strong key={currency}>{formatMoney(amount, currency)}</strong>
      ))}
    </div>
  );
}

function DashboardInsights({ invoices, loading, onOpenReports }) {
  const [payments, setPayments] = useState([]);
  const [paymentsLoading, setPaymentsLoading] = useState(true);
  const [paymentsError, setPaymentsError] = useState("");

  useEffect(() => {
    let isCurrent = true;
    getInvoicePayments()
      .then((records) => {
        if (!isCurrent) return;
        setPayments(records);
        setPaymentsError("");
      })
      .catch((requestError) => {
        if (!isCurrent) return;
        setPaymentsError(
          requestError.response
            ? `Could not load payment insights (HTTP ${requestError.response.status}).`
            : "Could not load payment insights."
        );
      })
      .finally(() => {
        if (isCurrent) setPaymentsLoading(false);
      });

    return () => {
      isCurrent = false;
    };
  }, [invoices]);

  const paidByInvoice = useMemo(
    () => paidAmountByInvoice(payments),
    [payments]
  );
  const agingSummary = useMemo(
    () => buildAgingSummary(invoices, paidByInvoice),
    [invoices, paidByInvoice]
  );
  const vendorSummary = useMemo(
    () => buildVendorSummary(invoices, paidByInvoice, 5),
    [invoices, paidByInvoice]
  );
  const paymentTracking = useMemo(
    () => buildPaymentTracking(invoices, payments, paidByInvoice),
    [invoices, paidByInvoice, payments]
  );

  const agingMax = Math.max(
    ...agingSummary.map((bucket) => bucket.primaryAmount),
    0
  );
  const busy = loading || paymentsLoading;

  return (
    <section className="dashboard-insights" aria-label="AP dashboard insights">
      <div className="dashboard-insights-heading">
        <div>
          <h2>Operational insights</h2>
          <p>
            Aging, vendor concentration, and payment progress for the current
            invoice set.
          </p>
        </div>
        {onOpenReports && (
          <button
            className="button secondary"
            type="button"
            onClick={onOpenReports}
          >
            Open full reports
          </button>
        )}
      </div>

      {paymentsError && (
        <div className="vendor-error" role="alert">
          {paymentsError}
        </div>
      )}

      <div className="dashboard-insights-grid">
        <article className="dashboard-insight-panel">
          <div className="dashboard-insight-title">
            <div className="stat-icon amber">
              <CalendarClock size={18} />
            </div>
            <div>
              <h3>Invoice aging</h3>
              <span>Outstanding approved payables by due date</span>
            </div>
          </div>
          {busy ? (
            <p className="dashboard-insight-empty">Loading aging...</p>
          ) : (
            <ul className="aging-list">
              {agingSummary.map((bucket) => {
                const width =
                  agingMax > 0
                    ? Math.max(4, (bucket.primaryAmount / agingMax) * 100)
                    : 0;
                return (
                  <li key={bucket.label}>
                    <div className="aging-row">
                      <span>{bucket.label}</span>
                      <strong>
                        {bucket.count} ·{" "}
                        {bucket.totals.length ? (
                          bucket.totals
                            .map(({ currency, amount }) =>
                              formatMoney(amount, currency)
                            )
                            .join(" · ")
                        ) : (
                          "—"
                        )}
                      </strong>
                    </div>
                    <div className="aging-bar-track" aria-hidden="true">
                      <div
                        className="aging-bar-fill"
                        style={{ width: `${width}%` }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </article>

        <article className="dashboard-insight-panel">
          <div className="dashboard-insight-title">
            <div className="stat-icon purple">
              <UsersRound size={18} />
            </div>
            <div>
              <h3>Vendor analytics</h3>
              <span>Top vendors by recorded invoice value</span>
            </div>
          </div>
          {busy ? (
            <p className="dashboard-insight-empty">Loading vendors...</p>
          ) : vendorSummary.length === 0 ? (
            <p className="dashboard-insight-empty">No vendor invoices yet.</p>
          ) : (
            <div className="table-scroll dashboard-insight-table">
              <table>
                <thead>
                  <tr>
                    <th>VENDOR</th>
                    <th>INVOICES</th>
                    <th>OUTSTANDING</th>
                  </tr>
                </thead>
                <tbody>
                  {vendorSummary.map((vendor) => (
                    <tr key={`${vendor.vendor}-${vendor.currency}`}>
                      <td>
                        <strong>{vendor.vendor}</strong>
                        <div className="subtext">
                          {formatMoney(vendor.invoiceAmount, vendor.currency)}{" "}
                          billed
                        </div>
                      </td>
                      <td>{vendor.count}</td>
                      <td className="amount">
                        {formatMoney(
                          vendor.outstandingAmount,
                          vendor.currency
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>

        <article className="dashboard-insight-panel">
          <div className="dashboard-insight-title">
            <div className="stat-icon green">
              <Banknote size={18} />
            </div>
            <div>
              <h3>Payment tracking</h3>
              <span>Open balances and recent recorded payments</span>
            </div>
          </div>
          {busy ? (
            <p className="dashboard-insight-empty">Loading payments...</p>
          ) : (
            <>
              <div className="payment-tracking-summary">
                <div>
                  <span>Outstanding</span>
                  <MoneyList totals={paymentTracking.outstandingTotals} />
                </div>
                <div>
                  <span>Paid this month</span>
                  <MoneyList totals={paymentTracking.paidThisMonth} />
                </div>
                <div>
                  <span>Approved awaiting payment</span>
                  <strong>{paymentTracking.openPaymentCount}</strong>
                </div>
              </div>

              <div className="payment-tracking-split">
                <div>
                  <h4>Largest open balances</h4>
                  {paymentTracking.outstandingInvoices.length === 0 ? (
                    <p className="dashboard-insight-empty">
                      No outstanding approved invoices.
                    </p>
                  ) : (
                    <ul className="compact-invoice-list">
                      {paymentTracking.outstandingInvoices.map((invoice) => (
                        <li key={invoice.id}>
                          <div>
                            <strong>{invoice.invoice_number}</strong>
                            <span>
                              {invoice.vendor_name}
                              {invoice.due_date
                                ? ` · due ${formatDate(invoice.due_date)}`
                                : ""}
                            </span>
                          </div>
                          <em>
                            {formatMoney(invoice.outstanding, invoice.currency)}
                          </em>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div>
                  <h4>Recent payments</h4>
                  {paymentTracking.recentPayments.length === 0 ? (
                    <p className="dashboard-insight-empty">
                      No payments recorded yet.
                    </p>
                  ) : (
                    <ul className="compact-invoice-list">
                      {paymentTracking.recentPayments.map((payment) => (
                        <li key={payment.id}>
                          <div>
                            <strong>{payment.invoice_number}</strong>
                            <span>
                              {payment.vendor_name} ·{" "}
                              {formatDate(payment.payment_date)}
                            </span>
                          </div>
                          <em>
                            {formatMoney(
                              payment.amount,
                              payment.currency || "INR"
                            )}
                          </em>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </>
          )}
        </article>
      </div>
    </section>
  );
}

export default DashboardInsights;
