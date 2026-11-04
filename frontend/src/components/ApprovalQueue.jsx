import { useEffect, useState } from "react";
import { Bell, CheckCircle2 } from "lucide-react";
import { formatDate, formatMoney } from "../utils/formatters";
import {
  getApprovalNotifications,
  markApprovalNotificationRead,
} from "../services/invoiceService";

function ApprovalQueue({ invoices, loading, onSelectInvoice, roles }) {
  const [notifications, setNotifications] = useState([]);
  const [notificationError, setNotificationError] = useState("");

  useEffect(() => {
    let active = true;
    getApprovalNotifications()
      .then((items) => {
        if (active) setNotifications(items);
      })
      .catch(() => {
        if (active) setNotificationError("Could not load approval notifications.");
      });
    return () => {
      active = false;
    };
  }, []);

  const isAdministrator = roles.includes("Administrator");
  const pendingInvoices = invoices.filter((invoice) => {
    if (invoice.status !== "PENDING_APPROVAL") return false;
    if (isAdministrator) return true;
    return invoice.approval_steps?.some(
      (step) => step.status === "PENDING" && roles.includes(step.role)
    );
  });

  async function dismissNotification(notification) {
    try {
      const updated = await markApprovalNotificationRead(notification.id);
      setNotifications((current) =>
        current.map((item) => item.id === updated.id ? updated : item)
      );
    } catch (requestError) {
      setNotificationError(
        requestError.response
          ? `Could not update notification (HTTP ${requestError.response.status}).`
          : "Could not connect to update the notification."
      );
    }
  }

  return (
    <section className="table-panel approval-queue">
      {notificationError && (
        <div className="vendor-error" role="alert">{notificationError}</div>
      )}
      {notifications.length > 0 && (
        <section className="approval-notifications" aria-label="Approval notifications">
          <h3><Bell size={16} /> Reminders and escalations</h3>
          {notifications.map((notification) => (
            <article
              className={`approval-notification ${notification.read_at ? "read" : ""}`}
              key={notification.id}
            >
              <div>
                <strong>{notification.notification_type === "ESCALATION" ? "Escalation" : "Reminder"} · {notification.invoice_number}</strong>
                <p>{notification.message}</p>
              </div>
              {!notification.read_at && (
                <button
                  type="button"
                  className="vendor-edit-button"
                  onClick={() => dismissNotification(notification)}
                >
                  Mark read
                </button>
              )}
            </article>
          ))}
        </section>
      )}
      <div className="panel-heading">
        <div>
          <div className="eyebrow">REVIEW WORKFLOW</div>
          <h2>Invoice approval queue</h2>
          <p>Invoices with validated details and matched purchase orders.</p>
        </div>
        <span className="record-count">{pendingInvoices.length} awaiting approval</span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>INVOICE</th>
              <th>VENDOR</th>
              <th>INVOICE DATE</th>
              <th>AMOUNT</th>
              <th>THREE-WAY MATCH</th>
              <th>REQUIRED APPROVALS</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="7" className="empty-state">Loading approval queue...</td></tr>
            ) : pendingInvoices.length === 0 ? (
              <tr>
                <td colSpan="7" className="empty-state">
                  <CheckCircle2 size={18} />
                  <span>No invoices are waiting for approval.</span>
                </td>
              </tr>
            ) : pendingInvoices.map((invoice) => (
              <tr key={invoice.id}>
                <td>
                  <div className="invoice-id">{invoice.invoice_number}</div>
                  <div className="subtext">ID #{invoice.id}</div>
                </td>
                <td>{invoice.vendor_name}</td>
                <td>{formatDate(invoice.invoice_date)}</td>
                <td className="amount">{formatMoney(invoice.total_amount, invoice.currency)}</td>
                <td>
                  <span className={`vendor-status ${(invoice.three_way_match?.status || "not_linked").toLowerCase()}`}>
                    {(invoice.three_way_match?.status || "NOT LINKED").replaceAll("_", " ")}
                  </span>
                </td>
                <td>
                  {invoice.approval_steps?.map((step) => (
                    <div className="subtext" key={step.id}>
                      {step.role}: {step.status.toLowerCase()}
                    </div>
                  ))}
                </td>
                <td>
                  <button
                    className="vendor-edit-button"
                    type="button"
                    onClick={() => onSelectInvoice(invoice)}
                  >
                    Review
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="approval-queue-note">
        Each configured approver role must approve before the invoice advances.
        Overdue steps generate in-app reminders and administrator escalations.
      </div>
    </section>
  );
}

export default ApprovalQueue;
