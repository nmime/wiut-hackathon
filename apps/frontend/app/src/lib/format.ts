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

// Keep editable amounts as decimal strings: grouping never changes their UZS scale.
export function formatAmountInputEdit(
  value: string,
  selectionStart = value.length,
  selectionEnd = selectionStart,
) {
  const ungroup = (text: string) => text.replace(/[,\s]/g, '');
  const raw = ungroup(value);
  if (!/^\d*(?:\.\d{0,2})?$/.test(raw)) return null;
  if (raw === '') return { value: '', selectionStart: 0, selectionEnd: 0 };
  const [integer = '', fraction = ''] = raw.split('.');
  const normalizedInteger = integer.replace(/^0+(?=\d)/, '') || '0';
  const removedZeros = Math.max(0, integer.length - normalizedInteger.length);
  const addedZero = integer === '' ? 1 : 0;
  const formatted =
    normalizedInteger.replace(/\B(?=(\d{3})+(?!\d))/g, ',') +
    (raw.includes('.') ? `.${fraction}` : '');
  const caret = (position: number) => {
    const prefixLength = ungroup(value.slice(0, position)).length;
    const count =
      prefixLength - Math.min(prefixLength, removedZeros) + addedZero;
    if (count === 0) return 0;
    let seen = 0;
    for (let index = 0; index < formatted.length; index++) {
      if (formatted[index] !== ',' && ++seen === count) return index + 1;
    }
    return formatted.length;
  };
  return {
    value: formatted,
    selectionStart: caret(selectionStart),
    selectionEnd: caret(selectionEnd),
  };
}

export function parseAmountInput(value: string) {
  if (value.trim() === '') return null;
  if (!isAmountPaste(value)) return NaN;
  const formatted = formatAmountInputEdit(value);
  return formatted ? Number(formatted.value.replaceAll(',', '')) : NaN;
}

// Unlike typing, pasted grouping must be unambiguous before it is normalized.
export function isAmountPaste(value: string) {
  return /^(?:\d+|\d{1,3}(?:,\d{3})+|\d{1,3}(?:[\s]\d{3})+)(?:\.\d{0,2})?$/.test(
    value.trim(),
  );
}

export function updateAmountInput(
  input: HTMLInputElement,
  previous: string,
  update: (next: string) => void,
) {
  const edited = formatAmountInputEdit(
    input.value,
    input.selectionStart ?? input.value.length,
    input.selectionEnd ?? input.value.length,
  );
  if (!edited) {
    // Recover the changed range before replacing the DOM value, which otherwise
    // moves the cursor to the end even when a middle character was rejected.
    const rejected = input.value;
    const start = input.selectionStart ?? rejected.length;
    const end = input.selectionEnd ?? start;
    const insertedLength = rejected.length - previous.length;
    const insertionStart = start - insertedLength;
    if (
      start === end &&
      insertedLength > 0 &&
      insertionStart >= 0 &&
      rejected.slice(0, insertionStart) + rejected.slice(start) === previous
    ) {
      input.value = previous;
      input.setSelectionRange(insertionStart, insertionStart);
      return;
    }
    let prefix = 0;
    while (
      prefix < previous.length &&
      prefix < rejected.length &&
      previous[prefix] === rejected[prefix]
    ) {
      prefix++;
    }
    let previousEnd = previous.length;
    let rejectedEnd = rejected.length;
    while (
      previousEnd > prefix &&
      rejectedEnd > prefix &&
      previous[previousEnd - 1] === rejected[rejectedEnd - 1]
    ) {
      previousEnd--;
      rejectedEnd--;
    }
    const restorePosition = (position: number) =>
      position <= prefix
        ? position
        : position >= rejectedEnd
          ? position - rejectedEnd + previousEnd
          : prefix;
    input.value = previous;
    if (previousEnd > prefix && rejectedEnd > prefix && start === end) {
      input.setSelectionRange(prefix, previousEnd);
    } else {
      input.setSelectionRange(restorePosition(start), restorePosition(end));
    }
    return;
  }
  input.value = edited.value;
  update(edited.value);
  input.setSelectionRange(edited.selectionStart, edited.selectionEnd);
}

export function skipAmountSeparator(input: HTMLInputElement, key: string) {
  const start = input.selectionStart;
  if (start === null || start !== input.selectionEnd) return;
  if (key === 'Backspace' && input.value[start - 1] === ',') {
    input.setSelectionRange(start - 1, start - 1);
  } else if (key === 'Delete' && input.value[start] === ',') {
    input.setSelectionRange(start + 1, start + 1);
  }
}

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
