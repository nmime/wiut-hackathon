import type {
  BusinessDetail,
  MonthlyCashflow,
  Transaction,
  ShowcaseProvenance,
} from '@wiut/contracts';

export interface StoredBusiness {
  id: string;
  name: string;
  sector: string;
  location: string;
  archetype: string;
  transactions: Transaction[];
  data_source: 'user_provided' | 'synthetic';
  amount_unit: 'UZS' | 'index';
  archived_at: string | Date | null;
  showcase_provenance?: ShowcaseProvenance | null;
}

export function monthlyCashflow(
  transactions: Transaction[],
): MonthlyCashflow[] {
  const months = new Map<string, MonthlyCashflow>();
  for (const transaction of transactions) {
    const month = transaction.ts.slice(0, 7);
    const row = months.get(month) ?? {
      month,
      inflow_index: 0,
      outflow_index: 0,
      surplus_index: 0,
    };
    if (transaction.direction === 'in')
      row.inflow_index += transaction.amount_index;
    else row.outflow_index += transaction.amount_index;
    months.set(month, row);
  }
  if (months.size === 0) return [];
  const ordered = [...months.keys()].sort();
  const cursor = new Date(`${ordered[0]}-01T00:00:00Z`);
  const lastMonthTime = new Date(`${ordered.at(-1)!}-01T00:00:00Z`).getTime();
  const result: MonthlyCashflow[] = [];
  while (cursor.getTime() <= lastMonthTime) {
    const month = cursor.toISOString().slice(0, 7);
    const row = months.get(month) ?? {
      month,
      inflow_index: 0,
      outflow_index: 0,
      surplus_index: 0,
    };
    const inflow = Math.round(row.inflow_index * 100) / 100;
    const outflow = Math.round(row.outflow_index * 100) / 100;
    result.push({
      month,
      inflow_index: inflow,
      outflow_index: outflow,
      surplus_index: Math.round((inflow - outflow) * 100) / 100,
    });
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  }
  return result;
}

export function businessDetail(business: StoredBusiness): BusinessDetail {
  const transactions = [...business.transactions].sort((a, b) =>
    a.ts.localeCompare(b.ts),
  );
  const monthly_cashflow = monthlyCashflow(transactions);
  const average = (rows: MonthlyCashflow[]) =>
    rows.reduce((sum, row) => sum + row.inflow_index, 0) /
    Math.max(1, rows.length);
  const start = average(monthly_cashflow.slice(0, 3));
  const end = average(monthly_cashflow.slice(-3));
  const ratio = start > 0 ? end / start : 1;
  return {
    id: business.id,
    name: business.name,
    sector: business.sector,
    location: business.location,
    archetype: business.archetype,
    history_months: monthly_cashflow.length,
    transaction_count: transactions.length,
    avg_monthly_inflow_index: Math.round(average(monthly_cashflow) * 100) / 100,
    avg_monthly_surplus_index:
      Math.round(
        (monthly_cashflow.reduce((sum, month) => sum + month.surplus_index, 0) /
          Math.max(1, monthly_cashflow.length)) *
          100,
      ) / 100,
    trend: ratio > 1.1 ? 'growing' : ratio < 0.9 ? 'declining' : 'stable',
    last_activity_date: transactions.at(-1)!.ts.slice(0, 10),
    data_source: business.data_source,
    amount_unit: business.amount_unit,
    showcase_provenance: business.showcase_provenance ?? null,
    archived_at: business.archived_at
      ? new Date(business.archived_at).toISOString()
      : null,
    latest_assessment: null,
    transactions,
    monthly_cashflow,
  };
}
