import {
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  FileText,
  Gauge,
  Timer,
} from "lucide-react";
import { formatMoney } from "../utils/formatters";

function StatsGrid({
  approvedCount,
  invoiceCount,
  loading,
  averageOcrConfidence,
  averageApprovalHours,
  pendingCount,
  totalAmount,
}) {
  return (
    <div className="stats-grid">
      <article className="stat-card">
        <div className="stat-top">
          <span>Total invoices</span>
          <div className="stat-icon blue"><FileText size={20} /></div>
        </div>
        <strong className="stat-value">{loading ? "—" : invoiceCount}</strong>
        <span className="stat-caption">All recorded invoices</span>
      </article>

      <article className="stat-card">
        <div className="stat-top">
          <span>Total invoice value</span>
          <div className="stat-icon purple"><CircleDollarSign size={20} /></div>
        </div>
        <strong className="stat-value">
          {loading ? "—" : formatMoney(totalAmount)}
        </strong>
        <span className="stat-caption">Combined recorded amount</span>
      </article>

      <article className="stat-card">
        <div className="stat-top">
          <span>Pending invoices</span>
          <div className="stat-icon amber"><Clock3 size={20} /></div>
        </div>
        <strong className="stat-value">{loading ? "—" : pendingCount}</strong>
        <span className="stat-caption">Awaiting review or approval</span>
      </article>

      <article className="stat-card">
        <div className="stat-top">
          <span>Approved invoices</span>
          <div className="stat-icon green"><CheckCircle2 size={20} /></div>
        </div>
        <strong className="stat-value">{loading ? "—" : approvedCount}</strong>
        <span className="stat-caption">Approved, excluding paid</span>
      </article>

      <article className="stat-card">
        <div className="stat-top">
          <span>Average OCR confidence</span>
          <div className="stat-icon blue"><Gauge size={20} /></div>
        </div>
        <strong className="stat-value">
          {loading || averageOcrConfidence === null
            ? "—"
            : `${averageOcrConfidence.toFixed(1)}%`}
        </strong>
        <span className="stat-caption">Average of available OCR scores</span>
      </article>

      <article className="stat-card">
        <div className="stat-top">
          <span>Invoice-to-approval</span>
          <div className="stat-icon amber"><Timer size={20} /></div>
        </div>
        <strong className="stat-value">
          {loading || averageApprovalHours === null
            ? "—"
            : `${averageApprovalHours.toFixed(1)} hrs`}
        </strong>
        <span className="stat-caption">Average for approved invoices</span>
      </article>
    </div>
  );
}

export default StatsGrid;
