function todayIsoDate() {
  const today = new Date();
  today.setMinutes(today.getMinutes() - today.getTimezoneOffset());
  return today.toISOString().slice(0, 10);
}

export function paidAmountByInvoice(payments) {
  const totals = new Map();
  payments.forEach((payment) => {
    const cents = Math.round(Number(payment.amount || 0) * 100);
    totals.set(payment.invoice, (totals.get(payment.invoice) || 0) + cents);
  });
  return totals;
}

export function buildAgingSummary(invoices, paidByInvoice, asOfDate = todayIsoDate()) {
  const buckets = [
    { label: "Not yet due", cents: new Map(), count: 0 },
    { label: "No due date", cents: new Map(), count: 0 },
    { label: "1–30 days", cents: new Map(), count: 0 },
    { label: "31–60 days", cents: new Map(), count: 0 },
    { label: "61–90 days", cents: new Map(), count: 0 },
    { label: "Over 90 days", cents: new Map(), count: 0 },
  ];
  const asOf = Date.parse(`${asOfDate}T00:00:00Z`);

  invoices
    .filter((invoice) => ["APPROVED", "PAID"].includes(invoice.status))
    .forEach((invoice) => {
      const totalCents = Math.round(Number(invoice.total_amount || 0) * 100);
      const paidCents = paidByInvoice.get(invoice.id) || 0;
      const outstandingCents = Math.max(0, totalCents - paidCents);
      if (outstandingCents === 0) return;

      const overdueDays = invoice.due_date
        ? Math.floor(
            (asOf - Date.parse(`${invoice.due_date}T00:00:00Z`)) / 86400000
          )
        : -1;

      let bucket;
      if (!invoice.due_date) {
        bucket = buckets[1];
      } else if (overdueDays <= 0) {
        bucket = buckets[0];
      } else if (overdueDays <= 30) {
        bucket = buckets[2];
      } else if (overdueDays <= 60) {
        bucket = buckets[3];
      } else if (overdueDays <= 90) {
        bucket = buckets[4];
      } else {
        bucket = buckets[5];
      }

      const currency = invoice.currency || "INR";
      bucket.cents.set(
        currency,
        (bucket.cents.get(currency) || 0) + outstandingCents
      );
      bucket.count += 1;
    });

  return buckets.map((bucket) => ({
    label: bucket.label,
    count: bucket.count,
    totals: Array.from(bucket.cents, ([currency, cents]) => ({
      currency,
      amount: cents / 100,
    })).sort((left, right) => left.currency.localeCompare(right.currency)),
    primaryAmount: Array.from(bucket.cents.values()).reduce(
      (sum, cents) => sum + cents,
      0
    ) / 100,
  }));
}

export function buildVendorSummary(invoices, paidByInvoice, limit = 5) {
  const groups = new Map();

  invoices.forEach((invoice) => {
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

  return Array.from(groups.values())
    .map((group) => ({
      ...group,
      invoiceAmount: group.invoiceCents / 100,
      paidAmount: group.paidCents / 100,
      outstandingAmount:
        Math.max(0, group.invoiceCents - group.paidCents) / 100,
    }))
    .sort(
      (left, right) =>
        right.invoiceCents - left.invoiceCents ||
        left.vendor.localeCompare(right.vendor)
    )
    .slice(0, limit);
}

export function buildPaymentTracking(invoices, payments, paidByInvoice) {
  const outstandingInvoices = invoices
    .filter((invoice) => ["APPROVED", "PAID"].includes(invoice.status))
    .map((invoice) => {
      const totalCents = Math.round(Number(invoice.total_amount || 0) * 100);
      const paidCents = paidByInvoice.get(invoice.id) || 0;
      const outstandingCents = Math.max(0, totalCents - paidCents);
      return {
        id: invoice.id,
        invoice_number: invoice.invoice_number,
        vendor_name: invoice.vendor_name,
        currency: invoice.currency || "INR",
        due_date: invoice.due_date,
        status: invoice.status,
        outstanding: outstandingCents / 100,
      };
    })
    .filter((invoice) => invoice.outstanding > 0)
    .sort((left, right) => right.outstanding - left.outstanding)
    .slice(0, 5);

  const fullOutstanding = invoices
    .filter((invoice) => ["APPROVED", "PAID"].includes(invoice.status))
    .reduce((totals, invoice) => {
      const totalCents = Math.round(Number(invoice.total_amount || 0) * 100);
      const paidCents = paidByInvoice.get(invoice.id) || 0;
      const outstandingCents = Math.max(0, totalCents - paidCents);
      if (outstandingCents === 0) return totals;
      const currency = invoice.currency || "INR";
      totals.set(currency, (totals.get(currency) || 0) + outstandingCents);
      return totals;
    }, new Map());

  const recentPayments = [...payments]
    .sort((left, right) => {
      const byDate = String(right.payment_date).localeCompare(
        String(left.payment_date)
      );
      if (byDate !== 0) return byDate;
      return (right.id || 0) - (left.id || 0);
    })
    .slice(0, 5);

  const paidThisMonthByCurrency = new Map();
  const monthPrefix = todayIsoDate().slice(0, 7);
  payments.forEach((payment) => {
    if (!String(payment.payment_date || "").startsWith(monthPrefix)) return;
    const currency = payment.currency || "INR";
    const cents = Math.round(Number(payment.amount || 0) * 100);
    paidThisMonthByCurrency.set(
      currency,
      (paidThisMonthByCurrency.get(currency) || 0) + cents
    );
  });

  return {
    outstandingInvoices,
    outstandingTotals: Array.from(fullOutstanding, ([currency, cents]) => ({
      currency,
      amount: cents / 100,
    })).sort((left, right) => left.currency.localeCompare(right.currency)),
    recentPayments,
    paidThisMonth: Array.from(
      paidThisMonthByCurrency,
      ([currency, cents]) => ({
        currency,
        amount: cents / 100,
      })
    ).sort((left, right) => left.currency.localeCompare(right.currency)),
    openPaymentCount: invoices.filter((invoice) =>
      ["APPROVED"].includes(invoice.status)
    ).length,
  };
}
