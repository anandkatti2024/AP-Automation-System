import { useEffect, useMemo, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import {
  getAuditEvents,
  getInvoicePayments,
  getInvoices,
} from "../services/invoiceService";
import { formatDate, formatMoney } from "../utils/formatters";

function todayValue() {
  const today = new Date();
  today.setMinutes(today.getMinutes() - today.getTimezoneOffset());
  return today.toISOString().slice(0, 10);
}

function yearStartValue() {
  return `${todayValue().slice(0, 4)}-01-01`;
}

function csvCell(value) {
  const rawText = value == null ? "" : String(value);
  const text = /^[=+\-@]/.test(rawText) ? `'${rawText}` : rawText;
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadCsv(filename, headers, rows) {
  const content = [headers, ...rows]
    .map((row) => row.map(csvCell).join(","))
    .join("\r\n");
  const blob = new Blob(["\uFEFF", content], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function amountByCurrency(records, amountForRecord) {
  const totals = new Map();
  records.forEach((record) => {
    const currency = record.currency || "INR";
    const cents = Math.round(Number(amountForRecord(record) || 0) * 100);
    totals.set(currency, (totals.get(currency) || 0) + cents);
  });
  return Array.from(totals, ([currency, cents]) => ({
    currency,
    amount: cents / 100,
  })).sort((left, right) => left.currency.localeCompare(right.currency));
}

function ReportTotals({ title, records, amountForRecord }) {
  const totals = amountByCurrency(records, amountForRecord);
  return (
    <article className="report-card">
      <h3>{title}</h3>
      {totals.length ? (
        <div className="report-total-list">
          {totals.map(({ currency, amount }) => (
            <strong key={currency}>{formatMoney(amount, currency)}</strong>
          ))}
        </div>
      ) : (
        <strong>—</strong>
      )}
      <span>{records.length} record{records.length === 1 ? "" : "s"}</span>
    </article>
  );
}

function Reports() {
  const [invoices, setInvoices] = useState([]);
  const [payments, setPayments] = useState([]);
  const [auditEvents, setAuditEvents] = useState([]);
  const [startDate, setStartDate] = useState(yearStartValue);
  const [endDate, setEndDate] = useState(todayValue);
  const [asOfDate, setAsOfDate] = useState(todayValue);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadReports() {
    setLoading(true);
    setError("");
    try {
      const [invoiceRecords, paymentRecords, auditRecords] = await Promise.all([
        getInvoices(),
        getInvoicePayments(),
        getAuditEvents(),
      ]);
      setInvoices(invoiceRecords);
      setPayments(paymentRecords);
      setAuditEvents(auditRecords);
    } catch (requestError) {
      setError(
        requestError.response
          ? `Could not load report data (HTTP ${requestError.response.status}).`
          : "Could not connect to the Django API."
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let isCurrent = true;
    Promise.all([getInvoices(), getInvoicePayments(), getAuditEvents()])
      .then(([invoiceRecords, paymentRecords, auditRecords]) => {
        if (!isCurrent) return;
        setInvoices(invoiceRecords);
        setPayments(paymentRecords);
        setAuditEvents(auditRecords);
      })
      .catch((requestError) => {
        if (!isCurrent) return;
        setError(
          requestError.response
            ? `Could not load report data (HTTP ${requestError.response.status}).`
            : "Could not connect to the Django API."
        );
      })
      .finally(() => {
        if (isCurrent) setLoading(false);
      });

    return () => {
      isCurrent = false;
    };
  }, []);

  const filteredInvoices = useMemo(
    () => invoices.filter((invoice) => {
      if (startDate && invoice.invoice_date && invoice.invoice_date < startDate) {
        return false;
      }
      if (endDate && invoice.invoice_date && invoice.invoice_date > endDate) {
        return false;
      }
      return true;
    }),
    [endDate, invoices, startDate]
  );

  const filteredPayments = useMemo(
    () => payments.filter((payment) => {
      if (startDate && payment.payment_date < startDate) return false;
      if (endDate && payment.payment_date > endDate) return false;
      return true;
    }),
    [endDate, payments, startDate]
  );

  const filteredAuditEvents = useMemo(
    () => auditEvents.filter((event) => {
      const eventDate = event.created_at.slice(0, 10);
      if (startDate && eventDate < startDate) return false;
      if (endDate && eventDate > endDate) return false;
      return true;
    }),
    [auditEvents, endDate, startDate]
  );

  const paidByInvoice = useMemo(() => {
    const totals = new Map();
    payments.forEach((payment) => {
      const cents = Math.round(Number(payment.amount) * 100);
      totals.set(payment.invoice, (totals.get(payment.invoice) || 0) + cents);
    });
    return totals;
  }, [payments]);

  const statusSummary = useMemo(() => {
    const groups = new Map();
    filteredInvoices.forEach((invoice) => {
      const key = `${invoice.currency || "INR"}:${invoice.status}`;
      const group = groups.get(key) || {
        currency: invoice.currency || "INR",
        status: invoice.status,
        count: 0,
        cents: 0,
      };
      group.count += 1;
      group.cents += Math.round(Number(invoice.total_amount || 0) * 100);
      groups.set(key, group);
    });
    return Array.from(groups.values()).sort(
      (left, right) =>
        left.currency.localeCompare(right.currency) ||
        left.status.localeCompare(right.status)
    );
  }, [filteredInvoices]);

  const exceptionInvoices = useMemo(
    () => filteredInvoices.filter(
      (invoice) => invoice.validation_errors?.length > 0
    ),
    [filteredInvoices]
  );

  const taxSummary = useMemo(() => {
    const groups = new Map();
    filteredInvoices.forEach((invoice) => {
      const gstin = invoice.vendor_gst_number || "";
      const currency = invoice.currency || "INR";
      const key = `${invoice.vendor_name}:${gstin}:${currency}`;
      const group = groups.get(key) || {
        vendor: invoice.vendor_name,
        gstin,
        currency,
        count: 0,
        taxableCents: 0,
        taxCents: 0,
        totalCents: 0,
      };
      group.count += 1;
      group.taxableCents += Math.round(Number(invoice.subtotal || 0) * 100);
      group.taxCents += Math.round(Number(invoice.tax_amount || 0) * 100);
      group.totalCents += Math.round(Number(invoice.total_amount || 0) * 100);
      groups.set(key, group);
    });
    return Array.from(groups.values()).sort(
      (left, right) =>
        left.vendor.localeCompare(right.vendor) ||
        left.currency.localeCompare(right.currency)
    );
  }, [filteredInvoices]);

  const vendorSummary = useMemo(() => {
    const groups = new Map();
    filteredInvoices.forEach((invoice) => {
      const currency = invoice.currency || "INR";
      const key = `${invoice.vendor_name}:${currency}`;
      const group = groups.get(key) || {
        vendor: invoice.vendor_name,
        currency,
        count: 0,
        invoiceCents: 0,
        paidCents: 0,
      };
      group.count += 1;
      group.invoiceCents += Math.round(Number(invoice.total_amount || 0) * 100);
      group.paidCents += paidByInvoice.get(invoice.id) || 0;
      groups.set(key, group);
    });
    return Array.from(groups.values()).sort(
      (left, right) =>
        right.invoiceCents - left.invoiceCents ||
        left.vendor.localeCompare(right.vendor)
    );
  }, [filteredInvoices, paidByInvoice]);

  const turnaroundHours = useMemo(() => {
    const durations = filteredInvoices.flatMap((invoice) => {
      const approved = invoice.approval_history?.find(
        (entry) => entry.action === "APPROVED"
      );
      if (!approved || !invoice.created_at) return [];
      const hours =
        (Date.parse(approved.created_at) - Date.parse(invoice.created_at)) /
        3600000;
      return Number.isFinite(hours) && hours >= 0 ? [hours] : [];
    });
    return durations.length
      ? durations.reduce((sum, hours) => sum + hours, 0) / durations.length
      : null;
  }, [filteredInvoices]);

  const averageOcrConfidence = useMemo(() => {
    const scores = filteredInvoices
      .filter((invoice) => invoice.ocr_confidence != null)
      .map((invoice) => Number(invoice.ocr_confidence))
      .filter((score) => Number.isFinite(score) && score >= 0);
    return scores.length
      ? scores.reduce((sum, score) => sum + score, 0) / scores.length
      : null;
  }, [filteredInvoices]);

  const agingSummary = useMemo(() => {
    const buckets = [
      { label: "Not yet due", days: null, cents: new Map(), count: 0 },
      { label: "No due date", days: null, cents: new Map(), count: 0 },
      { label: "1–30 days overdue", days: 30, cents: new Map(), count: 0 },
      { label: "31–60 days overdue", days: 60, cents: new Map(), count: 0 },
      { label: "61–90 days overdue", days: 90, cents: new Map(), count: 0 },
      { label: "Over 90 days overdue", days: Infinity, cents: new Map(), count: 0 },
    ];
    const asOf = Date.parse(`${asOfDate || todayValue()}T00:00:00Z`);

    filteredInvoices
      .filter((invoice) => ["APPROVED", "PAID"].includes(invoice.status))
      .forEach((invoice) => {
        const totalCents = Math.round(Number(invoice.total_amount || 0) * 100);
        const paidCents = paidByInvoice.get(invoice.id) || 0;
        const outstandingCents = Math.max(0, totalCents - paidCents);
        if (outstandingCents === 0) return;

        const overdueDays = invoice.due_date
          ? Math.floor(
              (asOf - Date.parse(`${invoice.due_date}T00:00:00Z`)) /
                86400000
            )
          : -1;
        const bucket = !invoice.due_date
          ? buckets[1]
          : overdueDays <= 0
            ? buckets[0]
            : buckets.find((item) => overdueDays <= item.days);
        const currency = invoice.currency || "INR";
        bucket.cents.set(
          currency,
          (bucket.cents.get(currency) || 0) + outstandingCents
        );
        bucket.count += 1;
      });

    return buckets.map((bucket) => ({
      ...bucket,
      totals: Array.from(bucket.cents, ([currency, cents]) => ({
        currency,
        amount: cents / 100,
      })).sort((left, right) => left.currency.localeCompare(right.currency)),
    }));
  }, [asOfDate, filteredInvoices, paidByInvoice]);

  function exportInvoices() {
    downloadCsv(
      "invoice-status-report.csv",
      [
        "Invoice number",
        "Vendor",
        "Invoice date",
        "Due date",
        "Currency",
        "Total amount",
        "Paid amount",
        "Outstanding amount",
        "Status",
      ],
      filteredInvoices.map((invoice) => {
        const totalCents = Math.round(Number(invoice.total_amount || 0) * 100);
        const paidCents = paidByInvoice.get(invoice.id) || 0;
        return [
          invoice.invoice_number,
          invoice.vendor_name,
          invoice.invoice_date,
          invoice.due_date,
          invoice.currency,
          (totalCents / 100).toFixed(2),
          (paidCents / 100).toFixed(2),
          (Math.max(0, totalCents - paidCents) / 100).toFixed(2),
          invoice.status,
        ];
      })
    );
  }

  function exportPayments() {
    downloadCsv(
      "payment-register.csv",
      [
        "Payment date",
        "Invoice number",
        "Vendor",
        "Currency",
        "Amount",
        "Method",
        "Reference",
        "Recorded by",
        "Notes",
      ],
      filteredPayments.map((payment) => [
        payment.payment_date,
        payment.invoice_number,
        payment.vendor_name,
        payment.currency,
        Number(payment.amount).toFixed(2),
        payment.payment_method,
        payment.payment_reference,
        payment.actor_name,
        payment.notes,
      ])
    );
  }

  function exportExceptions() {
    downloadCsv(
      "invoice-exceptions-report.csv",
      ["Invoice number", "Vendor", "Invoice date", "Currency", "Total amount", "Status", "Exceptions"],
      exceptionInvoices.map((invoice) => [
        invoice.invoice_number,
        invoice.vendor_name,
        invoice.invoice_date,
        invoice.currency,
        Number(invoice.total_amount || 0).toFixed(2),
        invoice.status,
        invoice.validation_errors.join("; "),
      ])
    );
  }

  function exportTaxSummary() {
    downloadCsv(
      "gst-tax-report.csv",
      ["Vendor", "GSTIN", "Currency", "Invoices", "Taxable amount", "Tax amount", "Invoice total"],
      taxSummary.map((group) => [
        group.vendor,
        group.gstin,
        group.currency,
        group.count,
        (group.taxableCents / 100).toFixed(2),
        (group.taxCents / 100).toFixed(2),
        (group.totalCents / 100).toFixed(2),
      ])
    );
  }

  function exportAuditEvents() {
    downloadCsv(
      "audit-log.csv",
      ["Timestamp", "Entity type", "Record", "Action", "User", "Changes"],
      filteredAuditEvents.map((event) => [
        event.created_at,
        event.entity_type,
        event.entity_label,
        event.action,
        event.actor_name,
        JSON.stringify(event.changes),
      ])
    );
  }

  return (
    <section className="reports-page">
      <div className="reports-page-heading">
        <div>
          <div className="eyebrow">FINANCE OVERVIEW</div>
          <h1>Reports</h1>
          <p>Review invoice status, outstanding payables, and recorded payments.</p>
        </div>
        <button
          className="button secondary"
          type="button"
          onClick={loadReports}
          disabled={loading}
        >
          <RefreshCw size={16} /> Refresh
        </button>
      </div>

      <div className="report-filters">
        <label className="review-field">
          <span>From invoice/payment date</span>
          <input
            type="date"
            value={startDate}
            max={endDate || undefined}
            onChange={(event) => setStartDate(event.target.value)}
          />
        </label>
        <label className="review-field">
          <span>Through invoice/payment date</span>
          <input
            type="date"
            value={endDate}
            min={startDate || undefined}
            onChange={(event) => setEndDate(event.target.value)}
          />
        </label>
        <label className="review-field">
          <span>Aging as of</span>
          <input
            type="date"
            value={asOfDate}
            onChange={(event) => setAsOfDate(event.target.value)}
          />
        </label>
      </div>

      {error && <div className="vendor-error" role="alert">{error}</div>}
      {loading && <div className="report-loading">Loading report data...</div>}

      <div className="report-summary-grid">
        <ReportTotals
          title="Invoice value"
          records={filteredInvoices}
          amountForRecord={(invoice) => invoice.total_amount}
        />
        <ReportTotals
          title="Payments in period"
          records={filteredPayments}
          amountForRecord={(payment) => payment.amount}
        />
        <ReportTotals
          title="Outstanding approved invoices"
          records={filteredInvoices.filter((invoice) => {
            if (!["APPROVED", "PAID"].includes(invoice.status)) return false;
            const totalCents = Math.round(
              Number(invoice.total_amount || 0) * 100
            );
            return (paidByInvoice.get(invoice.id) || 0) < totalCents;
          })}
          amountForRecord={(invoice) =>
            Math.max(
              0,
              Number(invoice.total_amount || 0) -
                (paidByInvoice.get(invoice.id) || 0) / 100
            )
          }
        />
      </div>
      <div className="report-summary-grid">
        <ReportTotals
          title="Invoices with exceptions"
          records={exceptionInvoices}
          amountForRecord={(invoice) => invoice.total_amount}
        />
        <article className="report-card">
          <h3>Average OCR confidence</h3>
          <strong>{averageOcrConfidence === null ? "—" : `${averageOcrConfidence.toFixed(1)}%`}</strong>
          <span>Average of available OCR scores</span>
        </article>
        <article className="report-card">
          <h3>Average invoice-to-approval time</h3>
          <strong>
            {turnaroundHours === null ? "—" : `${turnaroundHours.toFixed(1)} hrs`}
          </strong>
          <span>For invoices approved in the selected invoice period</span>
        </article>
      </div>

      <section className="vendor-list-panel">
        <div className="vendor-list-heading">
          <div>
            <h2>Invoice status summary</h2>
            <p>{filteredInvoices.length} invoice records for the selected period</p>
          </div>
          <button
            className="button secondary"
            type="button"
            onClick={exportInvoices}
            disabled={loading || filteredInvoices.length === 0}
          >
            <Download size={15} /> Export invoices
          </button>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>STATUS</th><th>CURRENCY</th><th>INVOICES</th><th>INVOICE VALUE</th></tr>
            </thead>
            <tbody>
              {statusSummary.length === 0 ? (
                <tr><td colSpan="4" className="empty-state">No invoices found for this period.</td></tr>
              ) : statusSummary.map((group) => (
                <tr key={`${group.currency}-${group.status}`}>
                  <td>{group.status.replaceAll("_", " ")}</td>
                  <td>{group.currency}</td>
                  <td>{group.count}</td>
                  <td className="amount">{formatMoney(group.cents / 100, group.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="vendor-list-panel">
        <div className="vendor-list-heading">
          <div>
            <h2>Exception report</h2>
            <p>{exceptionInvoices.length} invoices with validation issues in the selected period</p>
          </div>
          <button
            className="button secondary"
            type="button"
            onClick={exportExceptions}
            disabled={loading || exceptionInvoices.length === 0}
          >
            <Download size={15} /> Export exceptions
          </button>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>INVOICE</th><th>VENDOR</th><th>STATUS</th><th>EXCEPTIONS</th></tr>
            </thead>
            <tbody>
              {exceptionInvoices.length === 0 ? (
                <tr><td colSpan="4" className="empty-state">No invoice exceptions found for this period.</td></tr>
              ) : exceptionInvoices.map((invoice) => (
                <tr key={invoice.id}>
                  <td><span className="invoice-id">{invoice.invoice_number}</span></td>
                  <td>{invoice.vendor_name}</td>
                  <td>{invoice.status.replaceAll("_", " ")}</td>
                  <td>{invoice.validation_errors.join(" ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="vendor-list-panel">
        <div className="vendor-list-heading">
          <div>
            <h2>GST / tax report</h2>
            <p>Taxable value and tax amounts grouped by vendor, GSTIN, and currency.</p>
          </div>
          <button
            className="button secondary"
            type="button"
            onClick={exportTaxSummary}
            disabled={loading || taxSummary.length === 0}
          >
            <Download size={15} /> Export tax report
          </button>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>VENDOR</th><th>GSTIN</th><th>CURRENCY</th><th>INVOICES</th><th>TAXABLE</th><th>TAX</th><th>TOTAL</th></tr>
            </thead>
            <tbody>
              {taxSummary.length === 0 ? (
                <tr><td colSpan="7" className="empty-state">No tax data found for this period.</td></tr>
              ) : taxSummary.map((group) => (
                <tr key={`${group.vendor}-${group.gstin}-${group.currency}`}>
                  <td>{group.vendor}</td>
                  <td>{group.gstin || "—"}</td>
                  <td>{group.currency}</td>
                  <td>{group.count}</td>
                  <td className="amount">{formatMoney(group.taxableCents / 100, group.currency)}</td>
                  <td className="amount">{formatMoney(group.taxCents / 100, group.currency)}</td>
                  <td className="amount">{formatMoney(group.totalCents / 100, group.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="vendor-list-panel">
        <div className="vendor-list-heading">
          <div>
            <h2>Vendor analytics</h2>
            <p>Invoice volume and recorded payments by vendor and currency.</p>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>VENDOR</th><th>CURRENCY</th><th>INVOICES</th><th>INVOICE VALUE</th><th>PAID</th><th>OUTSTANDING</th></tr>
            </thead>
            <tbody>
              {vendorSummary.length === 0 ? (
                <tr><td colSpan="6" className="empty-state">No vendor invoices found for this period.</td></tr>
              ) : vendorSummary.map((group) => (
                <tr key={`${group.vendor}-${group.currency}`}>
                  <td>{group.vendor}</td>
                  <td>{group.currency}</td>
                  <td>{group.count}</td>
                  <td className="amount">{formatMoney(group.invoiceCents / 100, group.currency)}</td>
                  <td className="amount">{formatMoney(group.paidCents / 100, group.currency)}</td>
                  <td className="amount">{formatMoney(Math.max(0, group.invoiceCents - group.paidCents) / 100, group.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="vendor-list-panel">
        <div className="vendor-list-heading">
          <div>
            <h2>Payables aging</h2>
            <p>Approved invoices grouped by remaining balance and due date.</p>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>AGING BUCKET</th><th>INVOICES</th><th>OUTSTANDING BY CURRENCY</th></tr>
            </thead>
            <tbody>
              {agingSummary.map((bucket) => (
                <tr key={bucket.label}>
                  <td>{bucket.label}</td>
                  <td>{bucket.count}</td>
                  <td>
                    {bucket.totals.length ? bucket.totals.map(({ currency, amount }) => (
                      <div className="report-currency-total" key={currency}>
                        {formatMoney(amount, currency)}
                      </div>
                    )) : "—"}
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
            <h2>Payment register</h2>
            <p>{filteredPayments.length} payment records in the selected payment-date period</p>
          </div>
          <button
            className="button secondary"
            type="button"
            onClick={exportPayments}
            disabled={loading || filteredPayments.length === 0}
          >
            <Download size={15} /> Export payments
          </button>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>DATE</th><th>INVOICE</th><th>VENDOR</th><th>METHOD</th>
                <th>REFERENCE</th><th>AMOUNT</th><th>RECORDED BY</th>
              </tr>
            </thead>
            <tbody>
              {filteredPayments.length === 0 ? (
                <tr><td colSpan="7" className="empty-state">No payments found for this period.</td></tr>
              ) : filteredPayments.map((payment) => (
                <tr key={payment.id}>
                  <td>{formatDate(payment.payment_date)}</td>
                  <td><span className="invoice-id">{payment.invoice_number}</span></td>
                  <td>{payment.vendor_name}</td>
                  <td>{payment.payment_method.replaceAll("_", " ")}</td>
                  <td>{payment.payment_reference}</td>
                  <td className="amount">{formatMoney(payment.amount, payment.currency)}</td>
                  <td>{payment.actor_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="vendor-list-panel">
        <div className="vendor-list-heading">
          <div>
            <h2>Audit log</h2>
            <p>{filteredAuditEvents.length} recent recorded actions in the selected date range.</p>
          </div>
          <button
            className="button secondary"
            type="button"
            onClick={exportAuditEvents}
            disabled={loading || filteredAuditEvents.length === 0}
          >
            <Download size={15} /> Export audit log
          </button>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>TIME</th><th>RECORD</th><th>ACTION</th><th>USER</th><th>CHANGES</th>
              </tr>
            </thead>
            <tbody>
              {filteredAuditEvents.length === 0 ? (
                <tr><td colSpan="5" className="empty-state">No audit activity found for this period.</td></tr>
              ) : filteredAuditEvents.map((event) => (
                <tr key={event.id}>
                  <td>{new Date(event.created_at).toLocaleString("en-IN")}</td>
                  <td>{event.entity_type.replaceAll("_", " ")} · {event.entity_label}</td>
                  <td>{event.action.replaceAll("_", " ")}</td>
                  <td>{event.actor_name}</td>
                  <td><code>{JSON.stringify(event.changes)}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}

export default Reports;
