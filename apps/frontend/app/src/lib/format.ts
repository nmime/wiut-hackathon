import type { Assessment, BusinessDetail } from '@wiut/contracts';

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

export function downloadTransactions(business: BusinessDetail) {
  const rows = [
    'ts,direction,channel,amount_index',
    ...business.transactions.map(
      (t) => `${t.ts},${t.direction},${t.channel},${t.amount_index}`,
    ),
  ];
  const url = URL.createObjectURL(
    new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8' }),
  );
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${business.id}-transactions.csv`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
