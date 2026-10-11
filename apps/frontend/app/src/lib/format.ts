import type { Assessment, BusinessDetail } from '@wiut/contracts';

export type AmountUnit = 'UZS' | 'index';
export const amountUnitLabel = (unit: AmountUnit) =>
  unit === 'UZS' ? 'UZS' : 'amount index';
export const amountLabel = (value: number, unit: AmountUnit) =>
  `${indexNumber(value)} ${unit === 'UZS' ? 'UZS' : 'idx'}`;
export function businessExport(business: BusinessDetail) {
  return {
    name: business.name,
    sector: business.sector,
    location: business.location,
    data_source: business.data_source,
    amount_unit: business.amount_unit,
    ...(business.showcase_provenance
      ? { showcase_provenance: business.showcase_provenance }
      : {}),
    transactions: business.transactions.map(
      ({ amount_index, ...transaction }) => ({
        ...transaction,
        ...(business.amount_unit === 'UZS'
          ? { amount: amount_index }
          : { amount_index }),
      }),
    ),
  };
}

export const indexNumber = (value: number) =>
  new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(value);
export const compactNumber = (value: number) =>
  new Intl.NumberFormat('en-US', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);
export const dateLabel = (value: string) =>
  new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${value.slice(0, 10)}T00:00:00Z`));
export const timeLabel = (value: string) =>
  new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Tashkent',
  }).format(new Date(value));
export const monthLabel = (value: string) =>
  new Intl.DateTimeFormat('en-GB', {
    month: 'short',
    year: '2-digit',
    timeZone: 'UTC',
  }).format(new Date(`${value.slice(0, 7)}-01T00:00:00Z`));
export function forecastMonthLabel(asOfDate: string, monthOffset: number) {
  const month = new Date(`${asOfDate.slice(0, 7)}-01T00:00:00Z`);
  month.setUTCMonth(month.getUTCMonth() + monthOffset);
  return new Intl.DateTimeFormat('en-GB', {
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(month);
}
export const calendarMonthLabel = (month: number) =>
  new Intl.DateTimeFormat('en-GB', { month: 'long', timeZone: 'UTC' }).format(
    new Date(Date.UTC(2026, month - 1, 1)),
  );
export const assessmentLabel = (assessment: Assessment | null) =>
  !assessment
    ? 'Awaiting analysis'
    : assessment.status === 'failed'
      ? 'Analysis failed'
      : assessment.decision
        ? {
            approved: 'Approved',
            declined: 'Declined',
            needs_information: 'More information',
          }[assessment.decision.decision]
        : 'Review required';
export const eventLabel = (event: string) =>
  event.replaceAll('_', ' ').replace(/^./, (char) => char.toUpperCase());

export function downloadJson(filename: string, value: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }),
  );
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function transactionCsv(business: BusinessDetail) {
  const synthetic = business.data_source === 'synthetic';
  const provenance = business.showcase_provenance;
  const declaration = synthetic
    ? [
        'synthetic',
        business.amount_unit,
        provenance?.generator_version ?? 'legacy-synthetic',
        provenance?.seed ?? '',
        provenance?.scenario ?? '',
        provenance?.months ?? '',
        provenance?.end_month ?? '',
        provenance?.monthly_revenue_uzs ?? '',
        provenance?.batch_index ?? '',
      ]
    : [];
  const rows = [
    `${synthetic ? 'data_source,amount_unit,generator_version,seed,scenario,history_months,end_month,monthly_revenue_uzs,batch_index,' : ''}ts,direction,channel,${business.amount_unit === 'UZS' ? 'amount' : 'amount_index'}`,
    ...business.transactions.map((t) =>
      [...declaration, t.ts, t.direction, t.channel, t.amount_index].join(','),
    ),
  ];
  return rows.join('\n');
}

export function downloadTransactions(business: BusinessDetail) {
  const synthetic = business.data_source === 'synthetic';
  const url = URL.createObjectURL(
    new Blob([transactionCsv(business)], { type: 'text/csv;charset=utf-8' }),
  );
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${synthetic ? 'showcase-synthetic-' : ''}${business.id}-transactions-${business.amount_unit}.csv`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
