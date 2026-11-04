import {
  CheckCircle2,
  FileText,
  LayoutDashboard,
  ListChecks,
  Banknote,
  ChartNoAxesCombined,
  ShoppingCart,
  UsersRound,
} from "lucide-react";

function Sidebar({ activePage, onNavigate, roles, onLogout }) {
  const isAdministrator = roles.includes("Administrator");
  const canManagePurchasing =
    isAdministrator || roles.includes("AP Clerk");
  const canReviewVendors = isAdministrator || roles.includes("Approver");
  const canApprove =
    isAdministrator || roles.includes("Approver");
  const canRecordPayments =
    isAdministrator || roles.includes("Payment Clerk");

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">T</div>
        <div>
          <h2>Templegate</h2>
          <span>AP AUTOMATION</span>
        </div>
      </div>

      <div className="nav-label">WORKSPACE</div>
      <nav>
        <button
          className={`nav-item ${activePage === "dashboard" ? "active" : ""}`}
          type="button"
          onClick={() => onNavigate("dashboard")}
        >
          <LayoutDashboard size={19} /> Dashboard
        </button>
        <button
          className="nav-item"
          type="button"
          onClick={() => {
            onNavigate("dashboard");
            requestAnimationFrame(() =>
              document.getElementById("invoices")?.scrollIntoView({
                behavior: "smooth",
              })
            );
          }}
        >
          <FileText size={19} /> Invoices
        </button>
        {canApprove && <button
          className={`nav-item ${activePage === "approvals" ? "active" : ""}`}
          type="button"
          onClick={() => onNavigate("approvals")}
        >
          <ListChecks size={19} /> Approvals
        </button>}
        {canRecordPayments && <button
          className={`nav-item ${activePage === "payments" ? "active" : ""}`}
          type="button"
          onClick={() => onNavigate("payments")}
        >
          <Banknote size={19} /> Payments
        </button>}
        <button
          className={`nav-item ${activePage === "reports" ? "active" : ""}`}
          type="button"
          onClick={() => onNavigate("reports")}
        >
          <ChartNoAxesCombined size={19} /> Reports
        </button>
        {(canManagePurchasing || canReviewVendors) && <button
          className={`nav-item ${activePage === "vendors" ? "active" : ""}`}
          type="button"
          onClick={() => onNavigate("vendors")}
        >
          <UsersRound size={19} /> Vendors
        </button>}
        {canManagePurchasing && <button
          className={`nav-item ${activePage === "matching" ? "active" : ""}`}
          type="button"
          onClick={() => onNavigate("matching")}
        >
          <ShoppingCart size={19} /> PO Matching
        </button>}
      </nav>

      <div className="sidebar-bottom">
        <div className="sidebar-note">
          <div className="note-icon"><CheckCircle2 size={18} /></div>
          <strong>AP workspace</strong>
          <p>Signed in with role: {roles.join(", ") || "Read only"}</p>
        </div>
        <button className="sidebar-logout" type="button" onClick={onLogout}>
          Sign out
        </button>
        <span className="version">Templegate · Development</span>
      </div>
    </aside>
  );
}

export default Sidebar;
