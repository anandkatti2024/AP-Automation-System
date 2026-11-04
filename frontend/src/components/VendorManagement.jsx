import { useCallback, useEffect, useState } from "react";
import { Plus, RefreshCw, X } from "lucide-react";
import {
  approveVendor,
  createVendor,
  getVendors,
  rejectVendor,
  submitVendorForReview,
  updateVendor,
} from "../services/vendorService";

const EMPTY_VENDOR = {
  name: "",
  gstin: "",
  tax_id: "",
  contact_email: "",
  contact_phone: "",
  address: "",
  bank_account_name: "",
  bank_account_number: "",
  bank_ifsc: "",
  onboarding_status: "PENDING",
};

const STATUS_LABELS = {
  PENDING: "Pending",
  UNDER_REVIEW: "Under review",
  ACTIVE: "Active",
  REJECTED: "Rejected",
};

const ACTION_LABELS = {
  SUBMITTED: "Submitted for review",
  APPROVED: "Approved",
  REJECTED: "Rejected",
};

function getApiValidationErrors(error) {
  const detail = error.response?.data;
  const fieldErrors = {};
  const generalErrors = [];

  if (!detail || typeof detail !== "object" || Array.isArray(detail)) {
    return {
      fieldErrors,
      generalError: "Could not connect to the vendor API.",
    };
  }

  for (const [field, messages] of Object.entries(detail)) {
    const normalizedField = field === "bank_details" ? "bank_ifsc" : field;
    const text = Array.isArray(messages)
      ? messages.join(" ")
      : typeof messages === "string"
        ? messages
        : JSON.stringify(messages);

    if (normalizedField in EMPTY_VENDOR) {
      fieldErrors[normalizedField] = text;
    } else {
      generalErrors.push(text);
    }
  }

  return {
    fieldErrors,
    generalError: generalErrors.join(" "),
  };
}

function VendorManagement({ onMessage, roles = [], canManage = false }) {
  const [vendors, setVendors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [editingVendor, setEditingVendor] = useState(null);
  const [formOpen, setFormOpen] = useState(false);
  const [draft, setDraft] = useState(EMPTY_VENDOR);
  const [saving, setSaving] = useState(false);
  const [fieldErrors, setFieldErrors] = useState({});
  const [formError, setFormError] = useState("");
  const [reviewAction, setReviewAction] = useState(null);
  const [reviewComment, setReviewComment] = useState("");
  const [reviewError, setReviewError] = useState("");
  const [reviewSaving, setReviewSaving] = useState(false);
  const canReview = roles.includes("Approver") || roles.includes("Administrator");

  const fetchVendors = useCallback(() => getVendors(), []);

  const refreshVendors = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      setVendors(await fetchVendors());
    } catch (error) {
      setLoadError(
        error.response
          ? `Could not load vendors (HTTP ${error.response.status}).`
          : "Could not connect to the vendor API."
      );
    } finally {
      setLoading(false);
    }
  }, [fetchVendors]);

  useEffect(() => {
    let isCurrent = true;

    fetchVendors()
      .then((data) => {
        if (isCurrent) setVendors(data);
      })
      .catch((error) => {
        if (!isCurrent) return;
        setLoadError(
          error.response
            ? `Could not load vendors (HTTP ${error.response.status}).`
            : "Could not connect to the vendor API."
        );
      })
      .finally(() => {
        if (isCurrent) setLoading(false);
      });

    return () => {
      isCurrent = false;
    };
  }, [fetchVendors]);

  function startCreate() {
    setEditingVendor(null);
    setFormOpen(true);
    setDraft({ ...EMPTY_VENDOR });
    setFieldErrors({});
    setFormError("");
  }

  function startEdit(vendor) {
    setEditingVendor(vendor);
    setFormOpen(true);
    setDraft({
      name: vendor.name,
      gstin: vendor.gstin,
      tax_id: vendor.tax_id,
      contact_email: vendor.contact_email,
      contact_phone: vendor.contact_phone,
      address: vendor.address,
      bank_account_name: vendor.bank_account_name,
      bank_account_number: "",
      bank_ifsc: vendor.bank_ifsc,
      onboarding_status: vendor.onboarding_status,
    });
    setFieldErrors({});
    setFormError("");
  }

  function updateDraft(event) {
    const { name, value } = event.target;
    setDraft((current) => ({ ...current, [name]: value }));
    setFieldErrors((current) => {
      const fieldsToClear =
        name === "bank_account_number" || name === "bank_ifsc"
          ? [name, "bank_ifsc", "bank_account_number"]
          : [name];
      if (!fieldsToClear.some((field) => current[field])) return current;
      const next = { ...current };
      fieldsToClear.forEach((field) => delete next[field]);
      return next;
    });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setSaving(true);
    setFieldErrors({});
    setFormError("");

    const vendorData = {
      ...draft,
      name: draft.name.trim(),
      gstin: draft.gstin.trim().toUpperCase(),
      tax_id: draft.tax_id.trim(),
      bank_ifsc: draft.bank_ifsc.trim().toUpperCase(),
    };
    if (!vendorData.bank_account_number) {
      delete vendorData.bank_account_number;
    }

    try {
      if (editingVendor) {
        const updatedVendor = await updateVendor(editingVendor.id, vendorData);
        setVendors((current) =>
          current.map((vendor) =>
            vendor.id === updatedVendor.id ? updatedVendor : vendor
          )
        );
        onMessage("Vendor details updated.");
      } else {
        const createdVendor = await createVendor(vendorData);
        setVendors((current) => [...current, createdVendor]);
        onMessage("Vendor added to the master list.");
      }

      setEditingVendor(null);
      setFormOpen(false);
      setDraft({ ...EMPTY_VENDOR });
    } catch (error) {
      const validation = getApiValidationErrors(error);
      setFieldErrors(validation.fieldErrors);
      setFormError(validation.generalError);
    } finally {
      setSaving(false);
    }
  }

  async function handleOnboardingAction(event) {
    event.preventDefault();
    if (!reviewAction) return;
    setReviewSaving(true);
    setReviewError("");
    const action = {
      SUBMITTED: submitVendorForReview,
      APPROVED: approveVendor,
      REJECTED: rejectVendor,
    }[reviewAction.action];
    try {
      const updatedVendor = await action(
        reviewAction.vendor.id,
        reviewComment.trim()
      );
      setVendors((current) =>
        current.map((vendor) =>
          vendor.id === updatedVendor.id ? updatedVendor : vendor
        )
      );
      onMessage(
        reviewAction.action === "SUBMITTED"
          ? "Vendor submitted for onboarding review."
          : reviewAction.action === "APPROVED"
            ? "Vendor onboarding approved."
            : "Vendor onboarding rejected with the recorded reason."
      );
      setReviewAction(null);
      setReviewComment("");
    } catch (error) {
      const detail = error.response?.data;
      setReviewError(
        typeof detail === "object"
          ? Object.values(detail).flat().join(" ")
          : "Could not update vendor onboarding status."
      );
    } finally {
      setReviewSaving(false);
    }
  }

  function startOnboardingAction(vendor, action) {
    setReviewAction({ vendor, action });
    setReviewComment("");
    setReviewError("");
  }

  return (
    <section className="vendor-page">
      <div className="vendor-page-heading">
        <div>
          <div className="eyebrow">MASTER DATA</div>
          <h1>Vendor management</h1>
          <p>Maintain vendor tax, contact, bank and onboarding details.</p>
        </div>
        <div className="vendor-page-actions">
          <button
            className="button secondary"
            type="button"
            onClick={refreshVendors}
            disabled={loading}
          >
            <RefreshCw size={16} /> Refresh
          </button>
          {canManage && (
            <button
              className="button primary"
              type="button"
              onClick={startCreate}
            >
              <Plus size={17} /> Add vendor
            </button>
          )}
        </div>
      </div>

      {loadError && <div className="vendor-error" role="alert">{loadError}</div>}

      {reviewAction && (
        <form className="vendor-form-panel" onSubmit={handleOnboardingAction}>
          <div className="vendor-form-heading">
            <div>
              <h2>{ACTION_LABELS[reviewAction.action]}: {reviewAction.vendor.name}</h2>
              <p>
                {reviewAction.action === "REJECTED"
                  ? "Provide the reason for rejection."
                  : "Add an optional note to the onboarding history."}
              </p>
            </div>
            <button
              className="review-close"
              type="button"
              onClick={() => setReviewAction(null)}
              aria-label="Close onboarding review"
              disabled={reviewSaving}
            >
              <X size={18} />
            </button>
          </div>
          <label className="review-field">
            <span>{reviewAction.action === "REJECTED" ? "Rejection reason *" : "Review note"}</span>
            <textarea
              value={reviewComment}
              onChange={(event) => setReviewComment(event.target.value)}
              rows={3}
              maxLength={2000}
              required={reviewAction.action === "REJECTED"}
            />
          </label>
          {reviewError && <div className="vendor-error" role="alert">{reviewError}</div>}
          <div className="vendor-form-actions">
            <button
              className="button secondary"
              type="button"
              onClick={() => setReviewAction(null)}
              disabled={reviewSaving}
            >
              Cancel
            </button>
            <button
              className="button primary"
              type="submit"
              disabled={reviewSaving}
            >
              {reviewSaving ? "Saving..." : "Confirm"}
            </button>
          </div>
        </form>
      )}

      {formOpen && (
        <form className="vendor-form-panel" onSubmit={handleSubmit}>
          <div className="vendor-form-heading">
            <div>
              <h2>{editingVendor ? "Edit vendor" : "New vendor"}</h2>
              <p>Fields marked * are required.</p>
            </div>
            <button
              className="review-close"
              type="button"
              onClick={() => setFormOpen(false)}
              aria-label="Close vendor form"
            >
              <X size={18} />
            </button>
          </div>

          <div className="vendor-form-fields">
            <label className="review-field">
              <span>Vendor name *</span>
              <input
                name="name"
                value={draft.name}
                onChange={updateDraft}
                required
                maxLength={255}
                aria-invalid={Boolean(fieldErrors.name)}
                aria-describedby={fieldErrors.name ? "name-error" : undefined}
              />
              {fieldErrors.name && (
                <span className="vendor-field-error" id="name-error" role="alert">
                  {fieldErrors.name}
                </span>
              )}
            </label>
            <label className="review-field">
              <span>GSTIN</span>
              <input
                name="gstin"
                value={draft.gstin}
                onChange={updateDraft}
                maxLength={15}
                placeholder="15-character GSTIN"
                aria-invalid={Boolean(fieldErrors.gstin)}
                aria-describedby={fieldErrors.gstin ? "gstin-error" : undefined}
              />
              {fieldErrors.gstin && (
                <span className="vendor-field-error" id="gstin-error" role="alert">
                  {fieldErrors.gstin}
                </span>
              )}
            </label>
            <label className="review-field">
              <span>Other tax ID / TIN</span>
              <input
                name="tax_id"
                value={draft.tax_id}
                onChange={updateDraft}
                maxLength={50}
                aria-invalid={Boolean(fieldErrors.tax_id)}
                aria-describedby={fieldErrors.tax_id ? "tax-id-error" : undefined}
              />
              {fieldErrors.tax_id && (
                <span className="vendor-field-error" id="tax-id-error" role="alert">
                  {fieldErrors.tax_id}
                </span>
              )}
            </label>
            <label className="review-field">
              <span>Contact email</span>
              <input
                name="contact_email"
                type="email"
                value={draft.contact_email}
                onChange={updateDraft}
                aria-invalid={Boolean(fieldErrors.contact_email)}
                aria-describedby={fieldErrors.contact_email ? "contact-email-error" : undefined}
              />
              {fieldErrors.contact_email && (
                <span className="vendor-field-error" id="contact-email-error" role="alert">
                  {fieldErrors.contact_email}
                </span>
              )}
            </label>
            <label className="review-field">
              <span>Contact phone</span>
              <input
                name="contact_phone"
                value={draft.contact_phone}
                onChange={updateDraft}
                maxLength={30}
                aria-invalid={Boolean(fieldErrors.contact_phone)}
              />
              {fieldErrors.contact_phone && (
                <span className="vendor-field-error" role="alert">
                  {fieldErrors.contact_phone}
                </span>
              )}
            </label>
            <div className="review-field">
              <span>Onboarding status</span>
              <span>
                {STATUS_LABELS[editingVendor?.onboarding_status || "PENDING"]}
              </span>
              <small>Status changes through the review actions below.</small>
            </div>
            <label className="review-field vendor-field-full">
              <span>Address</span>
              <textarea
                name="address"
                value={draft.address}
                onChange={updateDraft}
                rows={2}
              />
            </label>
            <label className="review-field">
              <span>Bank account name</span>
              <input
                name="bank_account_name"
                value={draft.bank_account_name}
                onChange={updateDraft}
                aria-invalid={Boolean(fieldErrors.bank_account_name)}
              />
              {fieldErrors.bank_account_name && (
                <span className="vendor-field-error" role="alert">
                  {fieldErrors.bank_account_name}
                </span>
              )}
            </label>
            <label className="review-field">
              <span>Bank account number</span>
              <input
                name="bank_account_number"
                type="password"
                autoComplete="new-password"
                value={draft.bank_account_number}
                onChange={updateDraft}
                maxLength={64}
                placeholder={
                  editingVendor?.bank_account_last4
                    ? `Saved; ending ${editingVendor.bank_account_last4}`
                    : ""
                }
                aria-invalid={Boolean(fieldErrors.bank_account_number)}
                aria-describedby={
                  fieldErrors.bank_account_number
                    ? "bank-account-number-error"
                    : undefined
                }
              />
              {fieldErrors.bank_account_number && (
                <span
                  className="vendor-field-error"
                  id="bank-account-number-error"
                  role="alert"
                >
                  {fieldErrors.bank_account_number}
                </span>
              )}
            </label>
            <label className="review-field">
              <span>IFSC code</span>
              <input
                name="bank_ifsc"
                value={draft.bank_ifsc}
                onChange={updateDraft}
                maxLength={11}
                placeholder="e.g. HDFC0001234"
                aria-invalid={Boolean(fieldErrors.bank_ifsc)}
                aria-describedby={fieldErrors.bank_ifsc ? "bank-ifsc-error" : undefined}
              />
              {fieldErrors.bank_ifsc && (
                <span
                  className="vendor-field-error"
                  id="bank-ifsc-error"
                  role="alert"
                >
                  {fieldErrors.bank_ifsc}
                </span>
              )}
            </label>
          </div>

          {editingVendor?.bank_account_last4 && (
            <p className="bank-mask-note">
              The saved account number is hidden. Leave the field blank to keep
              the existing number.
            </p>
          )}

          {formError && <div className="vendor-error" role="alert">{formError}</div>}

          <div className="vendor-form-actions">
            <button
              className="button secondary"
              type="button"
              onClick={() => setFormOpen(false)}
              disabled={saving}
            >
              Cancel
            </button>
            <button className="button primary" type="submit" disabled={saving}>
              {saving ? "Saving..." : "Save vendor"}
            </button>
          </div>
        </form>
      )}

      <section className="vendor-list-panel">
        <div className="vendor-list-heading">
          <div>
            <h2>Vendor master</h2>
            <p>{vendors.length} vendor{vendors.length === 1 ? "" : "s"} recorded</p>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>VENDOR</th>
                <th>GSTIN / TAX ID</th>
                <th>CONTACT</th>
                <th>BANK DETAILS</th>
                <th>ONBOARDING</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan="6" className="empty-state">Loading vendors...</td></tr>
              ) : vendors.length === 0 ? (
                <tr>
                  <td colSpan="6" className="empty-state">
                    No vendors yet. Add a vendor to start your master list.
                  </td>
                </tr>
              ) : (
                vendors.map((vendor) => (
                  <tr key={vendor.id}>
                    <td>
                      <div className="invoice-id">{vendor.name}</div>
                      <div className="subtext">Vendor #{vendor.id}</div>
                    </td>
                    <td>
                      <div>{vendor.gstin || "—"}</div>
                      {vendor.tax_id && <div className="subtext">TIN: {vendor.tax_id}</div>}
                    </td>
                    <td>
                      <div>{vendor.contact_email || "—"}</div>
                      {vendor.contact_phone && (
                        <div className="subtext">{vendor.contact_phone}</div>
                      )}
                    </td>
                    <td>
                      <div>{vendor.bank_account_name || "—"}</div>
                      {vendor.bank_account_last4 && (
                        <div className="subtext">
                          Account ending {vendor.bank_account_last4}
                          {vendor.bank_ifsc ? ` · ${vendor.bank_ifsc}` : ""}
                        </div>
                      )}
                    </td>
                    <td>
                      <span className={`vendor-status ${vendor.onboarding_status.toLowerCase()}`}>
                        {STATUS_LABELS[vendor.onboarding_status] || vendor.onboarding_status}
                      </span>
                      {vendor.onboarding_history?.map((entry) => (
                        <div className="subtext" key={entry.id}>
                          {ACTION_LABELS[entry.action]} by {entry.actor_name}
                          {entry.comment ? `: ${entry.comment}` : ""}
                        </div>
                      ))}
                    </td>
                    <td>
                      {canManage && vendor.onboarding_status !== "UNDER_REVIEW" && (
                        <button
                          className="vendor-edit-button"
                          type="button"
                          onClick={() => startEdit(vendor)}
                        >
                          Edit
                        </button>
                      )}
                      {canManage &&
                        ["PENDING", "REJECTED"].includes(vendor.onboarding_status) && (
                          <button
                            className="vendor-edit-button"
                            type="button"
                            onClick={() => startOnboardingAction(vendor, "SUBMITTED")}
                          >
                            Submit for review
                          </button>
                        )}
                      {canReview && vendor.onboarding_status === "UNDER_REVIEW" && (
                        <>
                          <button
                            className="vendor-edit-button"
                            type="button"
                            onClick={() => startOnboardingAction(vendor, "APPROVED")}
                          >
                            Approve
                          </button>
                          <button
                            className="vendor-edit-button"
                            type="button"
                            onClick={() => startOnboardingAction(vendor, "REJECTED")}
                          >
                            Reject
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}

export default VendorManagement;
