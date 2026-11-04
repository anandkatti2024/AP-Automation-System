import { useCallback, useEffect, useState } from "react";
import InvoiceTable from "./components/InvoiceTable";
import InvoiceReviewModal from "./components/InvoiceReviewModal";
import ApprovalQueue from "./components/ApprovalQueue";
import MessageBanner from "./components/MessageBanner";
import PageHeader from "./components/PageHeader";
import Sidebar from "./components/Sidebar";
import StatsGrid from "./components/StatsGrid";
import DashboardInsights from "./components/DashboardInsights";
import Topbar from "./components/Topbar";
import VendorManagement from "./components/VendorManagement";
import PurchaseOrderMatching from "./components/PurchaseOrderMatching";
import PaymentManagement from "./components/PaymentManagement";
import Reports from "./components/Reports";
import LoginForm from "./components/LoginForm";
import { getAuthSession, login, logout, register } from "./services/authService";
import {
  getInvoices,
  updateInvoice,
  uploadInvoice,
  approveInvoice,
  rejectInvoice,
  submitInvoiceForApproval,
  importEmailInvoices,
  getQuickBooksAuthorizationUrl,
  createQuickBooksDraftBill,
} from "./services/invoiceService";
import "./App.css";

function App() {
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState("");
  const [selectedInvoice, setSelectedInvoice] = useState(null);
  const [activePage, setActivePage] = useState("dashboard");
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [loginLoading, setLoginLoading] = useState(false);
  const [authError, setAuthError] = useState("");

  const fetchInvoices = useCallback(() => getInvoices(), []);
  const replaceInvoices = useCallback((records) => {
    setInvoices(records);
  }, []);

  const refreshInvoices = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      setInvoices(await fetchInvoices());
    } catch {
      setError("Cannot connect to Django. Check that the backend is running.");
    } finally {
      setLoading(false);
    }
  }, [fetchInvoices]);

  useEffect(() => {
    let isCurrent = true;

    getAuthSession()
      .then(async (session) => {
        if (!isCurrent) return;
        const url = new URL(window.location.href);
        const integration = url.searchParams.get("integration");
        const integrationDetail = url.searchParams.get("detail");
        if (integration === "quickbooks-connected") {
          setMessage("QuickBooks is connected.");
        } else if (integration === "quickbooks-error") {
          setMessage(
            integrationDetail
              ? `QuickBooks connection failed: ${integrationDetail}`
              : "QuickBooks connection failed or was cancelled."
          );
        }
        if (integration) {
          url.searchParams.delete("integration");
          url.searchParams.delete("detail");
          window.history.replaceState({}, "", url);
        }
        if (!session.authenticated) return;
        setUser(session);
        try {
          const data = await fetchInvoices();
          if (isCurrent) {
            setInvoices(data);
            setError("");
          }
        } catch {
          if (isCurrent) {
            setError("Could not load invoices for this account.");
          }
        }
      })
      .catch((requestError) => {
        if (isCurrent) {
          setAuthError(
            requestError.response
              ? "Could not verify your session. Refresh and try again."
              : "Cannot connect to Django. Check that the backend is running."
          );
        }
      })
      .finally(() => {
        if (isCurrent) {
          setLoading(false);
          setAuthLoading(false);
        }
      });

    return () => {
      isCurrent = false;
    };
  }, [fetchInvoices]);

  const isAdministrator =
    user?.is_superuser || user?.roles?.includes("Administrator");
  const hasRole = (role) =>
    Boolean(isAdministrator || user?.roles?.includes(role));

  async function handleLogin(credentials) {
    setLoginLoading(true);
    setAuthError("");
    try {
      const session = await login(credentials);
      setUser(session);
      setLoading(true);
      setInvoices([]);
      setActivePage("dashboard");
      try {
        setInvoices(await fetchInvoices());
        setError("");
      } catch {
        setError("Signed in, but invoices could not be loaded.");
      }
    } catch (requestError) {
      const detail = requestError.response?.data?.detail;
      setAuthError(
        detail || "Could not sign in. Check your credentials and try again."
      );
      setUser(null);
    } finally {
      setLoading(false);
      setLoginLoading(false);
    }
  }

  async function handleRegister(credentials) {
    setLoginLoading(true);
    setAuthError("");
    try {
      const session = await register(credentials);
      setUser(session);
      setLoading(true);
      setInvoices([]);
      setActivePage("dashboard");
      try {
        setInvoices(await fetchInvoices());
        setError("");
      } catch {
        setError("Your account was created, but invoices could not be loaded.");
      }
    } catch (requestError) {
      const detail = requestError.response?.data?.detail;
      const passwordErrors = requestError.response?.data?.errors?.password;
      setAuthError(
        detail
          ? [detail, ...(passwordErrors || [])].join(" ")
          : "Could not create your account. Please try again."
      );
      setUser(null);
    } finally {
      setLoading(false);
      setLoginLoading(false);
    }
  }

  async function handleLogout() {
    try {
      await logout();
    } catch {
      setAuthError("Could not sign out. Please try again.");
      return;
    }
    setUser(null);
    setInvoices([]);
    setSelectedInvoice(null);
    setActivePage("dashboard");
    setAuthError("");
  }

  const filteredInvoices = invoices.filter((invoice) => {
    const term = search.toLowerCase();
    const matchesSearch =
      invoice.invoice_number.toLowerCase().includes(term) ||
      invoice.vendor_name.toLowerCase().includes(term);

    const matchesStatus =
      statusFilter === "ALL" || invoice.status === statusFilter;

    return matchesSearch && matchesStatus;
  });

  const totalAmount = invoices.reduce(
    (sum, invoice) => sum + Number(invoice.total_amount || 0),
    0
  );

  const pendingCount = invoices.filter((invoice) =>
    ["UPLOADED", "PROCESSING", "PENDING_REVIEW", "PENDING_APPROVAL"].includes(
      invoice.status
    )
  ).length;

  const approvedCount = invoices.filter(
    (invoice) => invoice.status === "APPROVED"
  ).length;
  const ocrScores = invoices
    .filter((invoice) => invoice.ocr_confidence != null)
    .map((invoice) => Number(invoice.ocr_confidence))
    .filter((score) => Number.isFinite(score) && score >= 0);
  const averageOcrConfidence = ocrScores.length
    ? ocrScores.reduce((sum, score) => sum + score, 0) / ocrScores.length
    : null;
  const approvalDurations = invoices.flatMap((invoice) => {
    const approval = invoice.approval_history?.find(
      (entry) => entry.action === "APPROVED"
    );
    if (!approval || !invoice.created_at) return [];
    const hours =
      (Date.parse(approval.created_at) - Date.parse(invoice.created_at)) /
      3600000;
    return Number.isFinite(hours) && hours >= 0 ? [hours] : [];
  });
  const averageApprovalHours = approvalDurations.length
    ? approvalDurations.reduce((sum, hours) => sum + hours, 0) /
      approvalDurations.length
    : null;

  if (authLoading) {
    return <main className="login-page"><p>Checking your session...</p></main>;
  }

  if (!user) {
    return (
      <LoginForm
        onLogin={handleLogin}
        onRegister={handleRegister}
        loading={loginLoading}
        error={authError}
      />
    );
  }

  async function handleUpload(files) {
    if (!files.length) return;
    const allowedTypes = [
      "application/pdf",
      "image/jpeg",
      "image/png",
      "image/tiff",
    ];

    const acceptedFiles = files.filter((file) => allowedTypes.includes(file.type));
    const rejectedFiles = files.filter((file) => !allowedTypes.includes(file.type));
    if (!acceptedFiles.length) {
      setMessage("Please select PDF, JPG, PNG or TIFF invoices.");
      return;
    }

    setUploading(true);
    setMessage("");
    const failures = [];
    let uploadedCount = 0;
    try {
      if (rejectedFiles.length) {
        failures.push(
          `${rejectedFiles.length} unsupported file${rejectedFiles.length === 1 ? "" : "s"}`
        );
      }
      for (const file of acceptedFiles) {
        try {
          await uploadInvoice(file);
          uploadedCount += 1;
        } catch (uploadError) {
          const detail = uploadError.response?.data;
          failures.push(
            `${file.name}: ${
              typeof detail === "object"
                ? JSON.stringify(detail)
                : "upload failed"
            }`
          );
        }
      }
      setMessage([
        uploadedCount
          ? `${uploadedCount} invoice${uploadedCount === 1 ? "" : "s"} uploaded. OCR extraction was attempted; review the extracted details.`
          : "",
        ...failures,
      ].filter(Boolean).join(" "));
      await refreshInvoices();
    } finally {
      setUploading(false);
    }
  }

  async function handleEmailImport(emailFile) {
    setUploading(true);
    setMessage("");
    try {
      const result = await importEmailInvoices(emailFile);
      const importedCount = result.imported?.length || 0;
      const skipped = result.unsupported_attachments?.length || 0;
      setMessage(
        `${importedCount} invoice attachment${importedCount === 1 ? "" : "s"} imported from email.${skipped ? ` ${skipped} attachment(s) were skipped.` : ""}`
      );
      await refreshInvoices();
    } catch (requestError) {
      const detail = requestError.response?.data;
      setMessage(
        detail
          ? `Email import failed: ${JSON.stringify(detail)}`
          : "Email import failed. Check the Django API."
      );
    } finally {
      setUploading(false);
    }
  }

  async function handleQuickBooksSync(invoiceId) {
    try {
      const invoice = await createQuickBooksDraftBill(invoiceId);
      setInvoices((currentInvoices) =>
        currentInvoices.map((item) =>
          item.id === invoice.id ? invoice : item
        )
      );
      setMessage(
        `Pending QuickBooks bill ${invoice.quickbooks_bill_id} created for ${invoice.invoice_number}. Review it in QuickBooks before posting or paying.`
      );
    } catch (requestError) {
      setMessage(
        requestError.response?.data
          ? `QuickBooks sync failed: ${JSON.stringify(requestError.response.data)}`
          : "QuickBooks sync failed. Check the Django API."
      );
    }
  }

  async function handleQuickBooksConnect() {
    try {
      const authorizationUrl = await getQuickBooksAuthorizationUrl();
      window.location.assign(authorizationUrl);
    } catch (requestError) {
      setMessage(
        requestError.response?.data
          ? `Could not connect QuickBooks: ${JSON.stringify(requestError.response.data)}`
          : "Could not connect QuickBooks. Check the Django API."
      );
    }
  }

  async function handleInvoiceSave(invoiceId, updates) {
    const updatedInvoice = await updateInvoice(invoiceId, updates);
    setInvoices((currentInvoices) =>
      currentInvoices.map((invoice) =>
        invoice.id === updatedInvoice.id ? updatedInvoice : invoice
      )
    );
    setSelectedInvoice(updatedInvoice);
    setMessage("Invoice corrections saved. Validation results have been updated.");
  }

  function applyInvoiceUpdate(updatedInvoice) {
    setInvoices((currentInvoices) =>
      currentInvoices.map((invoice) =>
        invoice.id === updatedInvoice.id ? updatedInvoice : invoice
      )
    );
    setSelectedInvoice(updatedInvoice);
  }

  async function handleSubmitForApproval(invoiceId, updates, comment) {
    const correctedInvoice = await updateInvoice(invoiceId, updates);
    applyInvoiceUpdate(correctedInvoice);
    const updatedInvoice = await submitInvoiceForApproval(invoiceId, comment);
    applyInvoiceUpdate(updatedInvoice);
    setMessage("Invoice submitted to the approval queue.");
  }

  async function handleApprovalDecision(action, invoiceId, comment) {
    const decision = action === "approve" ? approveInvoice : rejectInvoice;
    const updatedInvoice = await decision(invoiceId, comment);
    setInvoices((currentInvoices) =>
      currentInvoices.map((invoice) =>
        invoice.id === updatedInvoice.id ? updatedInvoice : invoice
      )
    );
    setSelectedInvoice(null);
    setMessage(
      action === "approve"
        ? "Invoice approved and recorded in its history."
        : "Invoice rejected and returned with the recorded reason."
    );
  }

  return (
    <div className="app-shell">
      <Sidebar
        activePage={activePage}
        onNavigate={setActivePage}
        onLogout={handleLogout}
        roles={isAdministrator ? ["Administrator"] : user.roles}
      />

      <main className="main-content" id="dashboard">
        <Topbar
          username={user.username}
          onLogout={handleLogout}
          pageTitle={
            activePage === "vendors"
              ? "Vendors"
              : activePage === "matching"
                ? "PO Matching"
                : activePage === "approvals"
                  ? "Approvals"
                  : activePage === "payments"
                    ? "Payments"
                    : activePage === "reports"
                      ? "Reports"
                  : "Dashboard"
          }
        />

        <section className="page-content">
          <MessageBanner
            message={message}
            onDismiss={() => setMessage("")}
          />
          <MessageBanner message={error} variant="error" />

          {activePage === "vendors" &&
          (hasRole("AP Clerk") || hasRole("Approver")) ? (
            <VendorManagement
              onMessage={setMessage}
              roles={isAdministrator ? ["Administrator"] : user.roles}
              canManage={hasRole("AP Clerk")}
            />
          ) : activePage === "matching" && hasRole("AP Clerk") ? (
            <PurchaseOrderMatching onMessage={setMessage} />
          ) : activePage === "approvals" && hasRole("Approver") ? (
            <ApprovalQueue
              invoices={invoices}
              loading={loading}
              onSelectInvoice={setSelectedInvoice}
              roles={isAdministrator ? ["Administrator"] : user.roles}
            />
          ) : activePage === "payments" && hasRole("Payment Clerk") ? (
            <PaymentManagement
              invoices={invoices}
              onInvoicesChange={replaceInvoices}
              onMessage={setMessage}
              onQuickBooksConnect={handleQuickBooksConnect}
              onQuickBooksSync={handleQuickBooksSync}
              isAdministrator={Boolean(isAdministrator)}
            />
          ) : activePage === "reports" ? (
            <Reports />
          ) : (
            <>
              <PageHeader
                onRefresh={refreshInvoices}
                onUpload={handleUpload}
                onImportEmail={handleEmailImport}
                uploading={uploading}
                canUpload={hasRole("AP Clerk")}
              />
              <StatsGrid
                approvedCount={approvedCount}
                averageApprovalHours={averageApprovalHours}
                averageOcrConfidence={averageOcrConfidence}
                invoiceCount={invoices.length}
                loading={loading}
                pendingCount={pendingCount}
                totalAmount={totalAmount}
              />
              <DashboardInsights
                invoices={invoices}
                loading={loading}
                onOpenReports={() => setActivePage("reports")}
              />
              <InvoiceTable
                invoices={filteredInvoices}
                loading={loading}
                onSelectInvoice={setSelectedInvoice}
                onSearchChange={setSearch}
                onStatusFilterChange={setStatusFilter}
                search={search}
                statusFilter={statusFilter}
                totalInvoiceCount={invoices.length}
              />
            </>
          )}

          <footer className="page-footer">
            <span>Templegate AP Automation</span>
            <span>React · Django REST Framework · PostgreSQL</span>
          </footer>
        </section>
      </main>
      {selectedInvoice && (
        <InvoiceReviewModal
          invoice={selectedInvoice}
          onClose={() => setSelectedInvoice(null)}
          onSave={handleInvoiceSave}
          onSubmitApproval={handleSubmitForApproval}
          onApprove={(invoiceId, comment) =>
            handleApprovalDecision("approve", invoiceId, comment)
          }
          onReject={(invoiceId, comment) =>
            handleApprovalDecision("reject", invoiceId, comment)
          }
          canEdit={hasRole("AP Clerk")}
          canSubmit={hasRole("AP Clerk")}
          canDecide={hasRole("Approver")}
        />
      )}
    </div>
  );
}

export default App;
