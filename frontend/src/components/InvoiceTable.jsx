import { ArrowUpRight, Search } from "lucide-react";
import { formatDate, formatMoney } from "../utils/formatters";

function statusClass(status) {
  if (status === "APPROVED" || status === "PAID") return "success";
  if (status === "REJECTED") return "danger";
  if (status === "PENDING_APPROVAL") return "warning";
  return "neutral";
}

function InvoiceTable({
  invoices,
  loading,
  onSelectInvoice,
  onSearchChange,
  onStatusFilterChange,
  search,
  statusFilter,
  totalInvoiceCount,
}) {
  return (
    <section className="table-panel" id="invoices">
      <div className="panel-heading">
        <div>
          <h2>Recent invoices</h2>
          <p>Invoice records retrieved from your Django API</p>
        </div>
        <span className="record-count">{invoices.length} records</span>
      </div>

      <div className="table-toolbar">
        <div className="search-box">
          <Search size={17} />
          <input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search invoice or vendor..."
          />
        </div>
        <select
          value={statusFilter}
          onChange={(event) => onStatusFilterChange(event.target.value)}
          aria-label="Filter invoices by status"
        >
          <option value="ALL">All statuses</option>
          <option value="UPLOADED">Uploaded</option>
          <option value="PROCESSING">Processing</option>
          <option value="PENDING_REVIEW">Pending review</option>
          <option value="PENDING_APPROVAL">Pending approval</option>
          <option value="APPROVED">Approved</option>
          <option value="REJECTED">Rejected</option>
          <option value="PAID">Paid</option>
        </select>
      </div>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>INVOICE</th>
              <th>VENDOR</th>
              <th>INVOICE DATE</th>
              <th>AMOUNT</th>
              <th>STATUS</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="6" className="empty-state">Loading invoices...</td></tr>
            ) : invoices.length === 0 ? (
              <tr>
                <td colSpan="6" className="empty-state">
                  No invoices match your search.
                </td>
              </tr>
            ) : (
              invoices.map((invoice) => (
                <tr key={invoice.id}>
                  <td>
                    <div className="invoice-id">{invoice.invoice_number}</div>
                    <div className="subtext">ID #{invoice.id}</div>
                  </td>
                  <td><span className="vendor-name">{invoice.vendor_name}</span></td>
                  <td>{formatDate(invoice.invoice_date)}</td>
                  <td className="amount">{formatMoney(invoice.total_amount)}</td>
                  <td>
                    <span className={`status-badge ${statusClass(invoice.status)}`}>
                      <span className="status-dot" />
                      {invoice.status.replaceAll("_", " ")}
                    </span>
                  </td>
                  <td>
                    <button
                      className="review-button"
                      type="button"
                      onClick={() => onSelectInvoice(invoice)}
                      aria-label={`Review invoice ${invoice.invoice_number}`}
                      title="Review invoice"
                    >
                      <ArrowUpRight size={17} className="row-arrow" />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="table-footer">
        <span>Showing {invoices.length} of {totalInvoiceCount} invoices</span>
        <span><span className="connection-dot" /> Live API data</span>
      </div>
    </section>
  );
}

export default InvoiceTable;
