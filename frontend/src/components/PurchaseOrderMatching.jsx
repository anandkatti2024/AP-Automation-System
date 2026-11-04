import { useCallback, useEffect, useState } from "react";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import {
  createPurchaseOrder,
  createGoodsReceipt,
  getGoodsReceipts,
  getInvoices,
  getPurchaseOrders,
  updateInvoice,
} from "../services/invoiceService";
import { getVendors } from "../services/vendorService";
import { formatMoney } from "../utils/formatters";

const EMPTY_LINE = {
  description: "",
  quantity: "1",
  unit_price: "",
};

function getErrorMessage(error) {
  if (error.response?.data) {
    return JSON.stringify(error.response.data);
  }
  return "Could not connect to the Django API.";
}

function PurchaseOrderMatching({ onMessage }) {
  const [purchaseOrders, setPurchaseOrders] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [vendors, setVendors] = useState([]);
  const [goodsReceipts, setGoodsReceipts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [linkDraft, setLinkDraft] = useState({});
  const [linkSavingId, setLinkSavingId] = useState(null);
  const [receiptOrderId, setReceiptOrderId] = useState("");
  const [receiptSaving, setReceiptSaving] = useState(false);
  const [receiptError, setReceiptError] = useState("");
  const [receiptForm, setReceiptForm] = useState({
    receipt_number: "",
    receipt_date: "",
    quantities: {},
  });
  const [form, setForm] = useState({
    po_number: "",
    vendor: "",
    currency: "INR",
    order_date: "",
    line_items: [{ ...EMPTY_LINE }],
  });

  const refreshData = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const [orders, invoiceRecords, vendorRecords, receiptRecords] = await Promise.all([
        getPurchaseOrders(),
        getInvoices(),
        getVendors(),
        getGoodsReceipts(),
      ]);
      setPurchaseOrders(orders);
      setInvoices(invoiceRecords);
      setVendors(vendorRecords);
      setGoodsReceipts(receiptRecords);
      setLinkDraft(
        Object.fromEntries(
          invoiceRecords.map((invoice) => [
            invoice.id,
            invoice.purchase_order ? String(invoice.purchase_order) : "",
          ])
        )
      );
    } catch (error) {
      setLoadError(
        error.response
          ? `Could not load matching data (HTTP ${error.response.status}).`
          : "Could not connect to the Django API."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let isCurrent = true;

    Promise.all([
      getPurchaseOrders(),
      getInvoices(),
      getVendors(),
      getGoodsReceipts(),
    ])
      .then(([orders, invoiceRecords, vendorRecords, receiptRecords]) => {
        if (!isCurrent) return;
        setPurchaseOrders(orders);
        setInvoices(invoiceRecords);
        setVendors(vendorRecords);
        setGoodsReceipts(receiptRecords);
        setLinkDraft(
          Object.fromEntries(
            invoiceRecords.map((invoice) => [
              invoice.id,
              invoice.purchase_order ? String(invoice.purchase_order) : "",
            ])
          )
        );
      })
      .catch((error) => {
        if (!isCurrent) return;
        setLoadError(
          error.response
            ? `Could not load matching data (HTTP ${error.response.status}).`
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

  function updateLine(index, field, value) {
    setForm((current) => ({
      ...current,
      line_items: current.line_items.map((line, lineIndex) =>
        lineIndex === index ? { ...line, [field]: value } : line
      ),
    }));
  }

  function addLine() {
    setForm((current) => ({
      ...current,
      line_items: [...current.line_items, { ...EMPTY_LINE }],
    }));
  }

  function removeLine(index) {
    setForm((current) => ({
      ...current,
      line_items: current.line_items.filter(
        (_, lineIndex) => lineIndex !== index
      ),
    }));
  }

  async function handleCreateOrder(event) {
    event.preventDefault();
    setSaving(true);
    setFormError("");

    const lineItems = form.line_items.map((line, index) => {
      const quantity = Number(line.quantity);
      const unitPrice = Number(line.unit_price);
      return {
        line_number: index + 1,
        description: line.description.trim(),
        quantity: line.quantity,
        unit_price: line.unit_price,
        line_total: (quantity * unitPrice).toFixed(2),
      };
    });

    try {
      const order = await createPurchaseOrder({
        ...form,
        vendor: Number(form.vendor),
        order_date: form.order_date || null,
        line_items: lineItems,
      });
      setPurchaseOrders((current) => [order, ...current]);
      setFormOpen(false);
      setForm({
        po_number: "",
        vendor: "",
        currency: "INR",
        order_date: "",
        line_items: [{ ...EMPTY_LINE }],
      });
      onMessage(`Purchase order ${order.po_number} created.`);
    } catch (error) {
      setFormError(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  async function handleLinkInvoice(invoice) {
    setLinkSavingId(invoice.id);
    setLoadError("");

    try {
      const poId = linkDraft[invoice.id] || null;
      const updatedInvoice = await updateInvoice(invoice.id, {
        purchase_order: poId ? Number(poId) : null,
      });
      setInvoices((current) =>
        current.map((item) =>
          item.id === updatedInvoice.id ? updatedInvoice : item
        )
      );
      onMessage(
        poId
          ? `Invoice ${invoice.invoice_number} linked to its purchase order.`
          : `Purchase order unlinked from invoice ${invoice.invoice_number}.`
      );
    } catch (error) {
      setLoadError(`Could not link purchase order: ${getErrorMessage(error)}`);
    } finally {
      setLinkSavingId(null);
    }
  }

  const receiptOrder = purchaseOrders.find(
    (order) => String(order.id) === receiptOrderId
  );

  function openReceiptForm(order) {
    setReceiptOrderId(String(order.id));
    setReceiptError("");
    setReceiptForm({
      receipt_number: "",
      receipt_date: "",
      quantities: Object.fromEntries(
        order.line_items.map((line) => [line.id, ""])
      ),
    });
  }

  async function handleCreateReceipt(event) {
    event.preventDefault();
    if (!receiptOrder) return;

    const lineItems = receiptOrder.line_items
      .filter((line) => Number(receiptForm.quantities[line.id]) > 0)
      .map((line) => ({
        purchase_order_line: line.id,
        quantity_received: receiptForm.quantities[line.id],
      }));

    if (!lineItems.length) {
      setReceiptError("Enter a received quantity for at least one PO line.");
      return;
    }

    setReceiptSaving(true);
    setReceiptError("");
    try {
      await createGoodsReceipt({
        receipt_number: receiptForm.receipt_number.trim(),
        purchase_order: receiptOrder.id,
        receipt_date: receiptForm.receipt_date || null,
        line_items: lineItems,
      });
      setReceiptOrderId("");
      await refreshData();
      onMessage(`Goods receipt recorded for ${receiptOrder.po_number}.`);
    } catch (error) {
      setReceiptError(`Could not save goods receipt: ${getErrorMessage(error)}`);
    } finally {
      setReceiptSaving(false);
    }
  }

  return (
    <section className="matching-page">
      <div className="matching-page-heading">
        <div>
          <div className="eyebrow">PURCHASING CONTROLS</div>
          <h1>Three-way PO matching</h1>
          <p>Compare the invoice, purchase order, and recorded goods receipts.</p>
        </div>
        <div className="matching-actions">
          <button
            className="button secondary"
            type="button"
            onClick={refreshData}
            disabled={loading}
          >
            <RefreshCw size={16} /> Refresh
          </button>
          <button
            className="button primary"
            type="button"
            onClick={() => {
              setFormError("");
              setFormOpen((open) => !open);
            }}
          >
            <Plus size={17} /> New purchase order
          </button>
        </div>
      </div>

      <div className="matching-guidance">
        Invoice descriptions and quantities are matched to the PO. Unit prices, line totals, and
        invoice subtotal allow         at most 0.01 in the PO currency for rounding. Currency
        and vendor must also match. Invoice quantities must not exceed quantities received.
      </div>
      {loadError && <div className="vendor-error" role="alert">{loadError}</div>}

      {formOpen && (
        <form className="vendor-form-panel" onSubmit={handleCreateOrder}>
          <div className="vendor-form-heading">
            <div>
              <h2>Create purchase order</h2>
              <p>Add the supplier and all authorized order lines.</p>
            </div>
          </div>
          <div className="vendor-form-fields">
            <label className="review-field">
              <span>PO number *</span>
              <input
                value={form.po_number}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    po_number: event.target.value,
                  }))
                }
                required
                maxLength={100}
              />
            </label>
            <label className="review-field">
              <span>Vendor *</span>
              <select
                value={form.vendor}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    vendor: event.target.value,
                  }))
                }
                required
              >
                <option value="">Select vendor</option>
                {vendors.map((vendor) => (
                  <option value={vendor.id} key={vendor.id}>
                    {vendor.name}{vendor.gstin ? ` · ${vendor.gstin}` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="review-field">
              <span>Currency *</span>
              <input
                value={form.currency}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    currency: event.target.value.toUpperCase(),
                  }))
                }
                required
                minLength={3}
                maxLength={3}
              />
            </label>
            <label className="review-field">
              <span>Order date</span>
              <input
                type="date"
                value={form.order_date}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    order_date: event.target.value,
                  }))
                }
              />
            </label>
          </div>

          <div className="po-lines-editor">
            <div className="po-lines-heading">
              <h3>Purchase order lines</h3>
              <button
                className="vendor-edit-button"
                type="button"
                onClick={addLine}
              >
                <Plus size={14} /> Add line
              </button>
            </div>
            {form.line_items.map((line, index) => (
              <div className="po-line-editor" key={index}>
                <label className="review-field po-description-field">
                  <span>Description *</span>
                  <input
                    value={line.description}
                    onChange={(event) =>
                      updateLine(index, "description", event.target.value)
                    }
                    required
                  />
                </label>
                <label className="review-field">
                  <span>Quantity *</span>
                  <input
                    type="number"
                    min="0.001"
                    step="0.001"
                    value={line.quantity}
                    onChange={(event) =>
                      updateLine(index, "quantity", event.target.value)
                    }
                    required
                  />
                </label>
                <label className="review-field">
                  <span>Unit price *</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={line.unit_price}
                    onChange={(event) =>
                      updateLine(index, "unit_price", event.target.value)
                    }
                    required
                  />
                </label>
                <div className="po-line-total">
                  Line total:{" "}
                  {formatMoney(
                    Number(line.quantity || 0) * Number(line.unit_price || 0),
                    form.currency || "INR"
                  )}
                </div>
                {form.line_items.length > 1 && (
                  <button
                    className="po-remove-line"
                    type="button"
                    onClick={() => removeLine(index)}
                    aria-label={`Remove line ${index + 1}`}
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
            ))}
          </div>

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
              {saving ? "Saving..." : "Create purchase order"}
            </button>
          </div>
        </form>
      )}

      <section className="vendor-list-panel">
        <div className="vendor-list-heading">
          <div>
            <h2>Purchase orders</h2>
            <p>{purchaseOrders.length} order{purchaseOrders.length === 1 ? "" : "s"} available to match</p>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>PO NUMBER</th>
                <th>VENDOR</th>
                <th>DATE</th>
                <th>LINES</th>
                <th>TOTAL</th>
                <th>STATUS</th>
                <th>RECEIPT</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan="7" className="empty-state">Loading purchase orders...</td></tr>
              ) : purchaseOrders.length === 0 ? (
                <tr><td colSpan="7" className="empty-state">No purchase orders created yet.</td></tr>
              ) : (
                purchaseOrders.map((order) => (
                  <tr key={order.id}>
                    <td><span className="invoice-id">{order.po_number}</span></td>
                    <td>{order.vendor_name}</td>
                    <td>{order.order_date || "—"}</td>
                    <td>{order.line_items.length}</td>
                    <td className="amount">
                      {formatMoney(order.total_amount, order.currency)}
                    </td>
                    <td>
                      <span className={`vendor-status ${order.status.toLowerCase()}`}>
                        {order.status}
                      </span>
                    </td>
                    <td>
                      {order.status === "OPEN" && (
                        <button
                          className="vendor-edit-button"
                          type="button"
                          onClick={() => openReceiptForm(order)}
                        >
                          Record receipt
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {receiptOrder && (
        <form className="vendor-form-panel" onSubmit={handleCreateReceipt}>
          <div className="vendor-form-heading">
            <div>
              <h2>Record goods receipt for {receiptOrder.po_number}</h2>
              <p>Enter the quantities received in this delivery. Leave other lines blank.</p>
            </div>
          </div>
          <div className="vendor-form-fields">
            <label className="review-field">
              <span>Receipt number *</span>
              <input
                value={receiptForm.receipt_number}
                onChange={(event) =>
                  setReceiptForm((current) => ({
                    ...current,
                    receipt_number: event.target.value,
                  }))
                }
                required
                maxLength={100}
              />
            </label>
            <label className="review-field">
              <span>Receipt date</span>
              <input
                type="date"
                value={receiptForm.receipt_date}
                onChange={(event) =>
                  setReceiptForm((current) => ({
                    ...current,
                    receipt_date: event.target.value,
                  }))
                }
              />
            </label>
          </div>
          <div className="po-lines-editor">
            <div className="po-lines-heading"><h3>Received quantities</h3></div>
            {receiptOrder.line_items.map((line) => (
              <label className="receipt-line" key={line.id}>
                <span>
                  {line.description}
                  <small>Ordered: {line.quantity}</small>
                </span>
                <input
                  type="number"
                  aria-label={`Quantity received for ${line.description}`}
                  min="0"
                  step="0.001"
                  value={receiptForm.quantities[line.id] || ""}
                  onChange={(event) =>
                    setReceiptForm((current) => ({
                      ...current,
                      quantities: {
                        ...current.quantities,
                        [line.id]: event.target.value,
                      },
                    }))
                  }
                />
              </label>
            ))}
          </div>
          {receiptError && <div className="vendor-error" role="alert">{receiptError}</div>}
          <div className="vendor-form-actions">
            <button
              className="button secondary"
              type="button"
              onClick={() => setReceiptOrderId("")}
              disabled={receiptSaving}
            >
              Cancel
            </button>
            <button className="button primary" type="submit" disabled={receiptSaving}>
              {receiptSaving ? "Saving..." : "Save goods receipt"}
            </button>
          </div>
        </form>
      )}

      <section className="vendor-list-panel">
        <div className="vendor-list-heading">
          <div>
            <h2>Goods receipts</h2>
            <p>{goodsReceipts.length} receipt{goodsReceipts.length === 1 ? "" : "s"} recorded against purchase orders</p>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>RECEIPT</th><th>PURCHASE ORDER</th><th>DATE</th><th>RECEIVED LINES</th></tr>
            </thead>
            <tbody>
              {goodsReceipts.length === 0 ? (
                <tr><td colSpan="4" className="empty-state">No goods receipts recorded yet.</td></tr>
              ) : goodsReceipts.map((receipt) => (
                <tr key={receipt.id}>
                  <td><span className="invoice-id">{receipt.receipt_number}</span></td>
                  <td>{receipt.purchase_order_number}</td>
                  <td>{receipt.receipt_date || "—"}</td>
                  <td>
                    {receipt.line_items.map((line) => (
                      <div className="receipt-summary-line" key={line.id}>
                        {line.description}: {line.quantity_received} / {line.quantity_ordered}
                      </div>
                    ))}
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
            <h2>Link invoices and review matches</h2>
            <p>Only purchase orders for the invoice supplier can be linked.</p>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>INVOICE</th>
                <th>VENDOR</th>
                <th>INVOICE SUBTOTAL</th>
                <th>PURCHASE ORDER</th>
                <th>THREE-WAY MATCH</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan="6" className="empty-state">Loading invoices...</td></tr>
              ) : invoices.length === 0 ? (
                <tr><td colSpan="6" className="empty-state">No invoices available to match.</td></tr>
              ) : (
                invoices.map((invoice) => {
                  const match = invoice.three_way_match || { status: "NOT_LINKED" };
                  const invoicePo = invoice.purchase_order
                    ? purchaseOrders.find(
                        (order) => order.id === invoice.purchase_order
                      )
                    : null;
                  const options = purchaseOrders.filter(
                    (order) =>
                      order.status === "OPEN" &&
                      (order.vendor === invoice.vendor_master_id ||
                        order.id === invoicePo?.id)
                  );
                  return (
                    <tr key={invoice.id}>
                      <td>
                        <div className="invoice-id">{invoice.invoice_number}</div>
                        <div className="subtext">ID #{invoice.id}</div>
                      </td>
                      <td>{invoice.vendor_name}</td>
                      <td className="amount">
                        {formatMoney(invoice.subtotal, invoice.currency)}
                      </td>
                      <td>
                        <select
                          className="po-link-select"
                          aria-label={`Purchase order for invoice ${invoice.invoice_number}`}
                          value={linkDraft[invoice.id] || ""}
                          onChange={(event) =>
                            setLinkDraft((current) => ({
                              ...current,
                              [invoice.id]: event.target.value,
                            }))
                          }
                        >
                          <option value="">Not linked</option>
                          {options.map((order) => (
                            <option value={order.id} key={order.id}>
                              {order.po_number} · {order.vendor_name}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <span className={`vendor-status ${match.status.toLowerCase()}`}>
                          {match.status.replaceAll("_", " ")}
                        </span>
                        {match.discrepancies?.length > 0 && (
                          <ul className="match-discrepancies">
                            {match.discrepancies.map((item, index) => (
                              <li key={`${item.type}-${index}`}>{item.message}</li>
                            ))}
                          </ul>
                        )}
                      </td>
                      <td>
                        <button
                          className="vendor-edit-button"
                          type="button"
                          disabled={
                            linkSavingId === invoice.id ||
                            String(invoice.purchase_order || "") ===
                              (linkDraft[invoice.id] || "")
                          }
                          onClick={() => handleLinkInvoice(invoice)}
                        >
                          {linkSavingId === invoice.id ? "Saving..." : "Save"}
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}

export default PurchaseOrderMatching;
