import { useState } from "react";

const editableFields = [
  { name: "invoice_number", label: "Invoice number", required: true },
  { name: "vendor_name", label: "Vendor name", required: true },
  { name: "vendor_gst_number", label: "Vendor GST number" },
  { name: "invoice_date", label: "Invoice date", type: "date" },
  { name: "due_date", label: "Due date", type: "date" },
  { name: "subtotal", label: "Subtotal", type: "number", required: true },
  { name: "tax_amount", label: "Tax amount", type: "number", required: true },
  { name: "total_amount", label: "Total amount", type: "number", required: true },
  { name: "currency", label: "Currency", required: true },
];

function InvoiceReviewModal({
  invoice,
  onClose,
  onSave,
  onSubmitApproval,
  onApprove,
  onReject,
  canEdit,
  canSubmit,
  canDecide,
}) {
  const [draft, setDraft] = useState(() =>
    Object.fromEntries(
      editableFields.map(({ name }) => [name, invoice[name] ?? ""])
    )
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [approvalComment, setApprovalComment] = useState("");
  const validationErrors = invoice.validation_errors || [];
  const validationStatus = invoice.validation_status || "NEEDS_REVIEW";
  const isPendingApproval = invoice.status === "PENDING_APPROVAL";
  const detailsLocked = ["PENDING_APPROVAL", "APPROVED", "PAID"].includes(
    invoice.status
  );
  const canRequestApproval = canSubmit &&
    ["UPLOADED", "PENDING_REVIEW", "REJECTED"].includes(invoice.status);
  const canEditDetails = canEdit && !detailsLocked;
  const canSubmitForApproval =
    canRequestApproval &&
    validationStatus === "VALID" &&
    invoice.three_way_match?.status === "THREE_WAY_MATCHED";

  async function handleSubmit(event) {
    event.preventDefault();
    setSaving(true);
    setError("");

    try {
      await onSave(invoice.id, draft);
    } catch (saveError) {
      const detail = saveError.response?.data;
      setError(
        typeof detail === "object"
          ? `Could not save changes: ${JSON.stringify(detail)}`
          : "Could not save changes. Check the Django API."
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleSubmitForApproval() {
    setSaving(true);
    setError("");
    try {
      await onSubmitApproval(invoice.id, draft, approvalComment);
    } catch (submitError) {
      const detail = submitError.response?.data;
      setError(
        detail
          ? `Could not submit for approval: ${JSON.stringify(detail)}`
          : "Could not submit for approval. Check the Django API."
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleDecision(decision) {
    if (decision === "reject" && !approvalComment.trim()) {
      setError("Enter a reason before rejecting this invoice.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (decision === "approve") {
        await onApprove(invoice.id, approvalComment);
      } else {
        await onReject(invoice.id, approvalComment);
      }
    } catch (decisionError) {
      const detail = decisionError.response?.data;
      setError(
        detail
          ? `Could not ${decision} invoice: ${JSON.stringify(detail)}`
          : `Could not ${decision} invoice. Check the Django API.`
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="review-overlay"
      onClick={onClose}
      role="presentation"
    >
      <section
        className="review-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="review-heading">
          <div>
            <div className="eyebrow">INVOICE REVIEW</div>
            <h2 id="review-title">{invoice.invoice_number}</h2>
            <p>
              {isPendingApproval
                ? "Review the validated invoice and record your approval decision."
                : "Check the extracted details and correct any mistakes."}
            </p>
          </div>
          <button
            className="review-close"
            type="button"
            onClick={onClose}
            aria-label="Close invoice review"
          >
            ×
          </button>
        </div>

        <div className={`review-validation ${validationStatus === "VALID" ? "valid" : ""}`}>
          <strong>
            {validationStatus === "VALID" ? "Validation passed" : "Needs review"}
          </strong>
          {validationErrors.length > 0 ? (
            <ul>
              {validationErrors.map((validationError) => (
                <li key={validationError}>{validationError}</li>
              ))}
            </ul>
          ) : (
            <p>No validation issues were found.</p>
          )}
        </div>

        {invoice.ocr_confidence != null && (
          <p className="review-confidence">
            OCR confidence: <strong>{invoice.ocr_confidence}%</strong>
          </p>
        )}

        {error && <div className="review-error" role="alert">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="review-fields">
            {editableFields.map(({ name, label, type = "text", required }) => (
              <label className="review-field" key={name}>
                <span>{label}{required ? " *" : ""}</span>
                <input
                  type={type}
                  step={type === "number" ? "0.01" : undefined}
                  value={draft[name]}
                  required={required}
                  disabled={detailsLocked}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      [name]: event.target.value,
                    }))
                  }
                />
              </label>
            ))}
          </div>

          <section className="line-items-section" aria-labelledby="line-items-title">
            <div className="line-items-heading">
              <h3 id="line-items-title">Extracted line items</h3>
              <span>{invoice.line_items?.length || 0} items</span>
            </div>
            {invoice.line_items?.length ? (
              <div className="line-items-scroll">
                <table className="line-items-table">
                  <thead>
                    <tr>
                      <th>DESCRIPTION</th>
                      <th>QTY</th>
                      <th>UNIT PRICE</th>
                      <th>LINE TOTAL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {invoice.line_items.map((item) => (
                      <tr key={item.id ?? item.line_number}>
                        <td>{item.description}</td>
                        <td>{item.quantity}</td>
                        <td>{item.unit_price}</td>
                        <td>{item.line_total}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="line-items-empty">
                No line items were detected. Verify the source invoice and OCR text.
              </p>
            )}
          </section>

          {invoice.ocr_text && (
            <details className="ocr-text-details">
              <summary>View extracted OCR text</summary>
              <pre>{invoice.ocr_text}</pre>
            </details>
          )}

          {canEditDetails && (
            <div className="review-actions">
              <button
                className="button secondary"
                type="button"
                onClick={onClose}
                disabled={saving}
              >
                Close
              </button>
              <button className="button primary" type="submit" disabled={saving}>
                {saving ? "Saving..." : "Save corrections"}
              </button>
            </div>
          )}
        </form>

        {(canRequestApproval || (isPendingApproval && canDecide)) && (
          <section className="approval-actions" aria-label="Approval actions">
            <label className="review-field">
              <span>
                {isPendingApproval ? "Decision comment" : "Submission comment"}
                {isPendingApproval ? " (required for rejection)" : ""}
              </span>
              <textarea
                value={approvalComment}
                maxLength={2000}
                rows={3}
                onChange={(event) => setApprovalComment(event.target.value)}
                placeholder={
                  isPendingApproval
                    ? "Add a note or explain why this invoice is being rejected"
                    : "Optional note for the approver"
                }
              />
            </label>
            <div className="review-actions">
              {isPendingApproval && canDecide ? (
                <>
                  <button
                    className="button secondary reject-button"
                    type="button"
                    onClick={() => handleDecision("reject")}
                    disabled={saving || !approvalComment.trim()}
                  >
                    {saving ? "Saving..." : "Reject invoice"}
                  </button>
                  <button
                    className="button primary"
                    type="button"
                    onClick={() => handleDecision("approve")}
                    disabled={saving}
                  >
                    {saving ? "Saving..." : "Approve invoice"}
                  </button>
                </>
              ) : (
                <>
                  {!canSubmitForApproval && (
                    <p className="approval-readiness">
                      Resolve all validation issues and link a purchase order
                      with a complete goods receipt before submitting.
                    </p>
                  )}
                  <button
                    className="button primary"
                    type="button"
                    onClick={handleSubmitForApproval}
                    disabled={saving || !canSubmitForApproval}
                    title={
                      canSubmitForApproval
                        ? "Submit this validated invoice for approval"
                        : "Resolve validation issues and achieve a three-way match first"
                    }
                  >
                    {saving ? "Submitting..." : "Submit for approval"}
                  </button>
                </>
              )}
            </div>
          </section>
        )}

        {invoice.approval_history?.length > 0 && (
          <section className="approval-history" aria-labelledby="approval-history-title">
            <h3 id="approval-history-title">Approval history</h3>
            <ol>
              {invoice.approval_history.map((entry) => (
                <li key={entry.id}>
                  <div>
                    <strong>{entry.action.replaceAll("_", " ")}</strong>
                    <span>{entry.actor_name} · {new Date(entry.created_at).toLocaleString()}</span>
                  </div>
                  {entry.comment && <p>{entry.comment}</p>}
                </li>
              ))}
            </ol>
          </section>
        )}

        <div className="review-modal-footer-actions">
          <button className="button secondary" type="button" onClick={onClose} disabled={saving}>
            Close review
          </button>
        </div>
      </section>
    </div>
  );
}

export default InvoiceReviewModal;
