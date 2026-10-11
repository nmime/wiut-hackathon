import {
  BusinessImportSchema,
  UserTransactionSchema,
  type BusinessImport,
} from '@wiut/contracts';

export type ImportFormat = 'json' | 'csv';
export type ImportTransaction = {
  ts: string;
  direction: 'in' | 'out';
  channel: 'card' | 'transfer' | 'qr' | 'cash_in' | 'other';
  amount: number;
};
export const MAX_IMPORT_BYTES = 3_000_000;
const MAX_TRANSACTIONS = 20_000;
const columns = ['ts', 'direction', 'channel', 'amount'];

export class ImportError extends Error {}

function checkSize(text: string) {
  if (new TextEncoder().encode(text).byteLength > MAX_IMPORT_BYTES)
    throw new ImportError(
      'Transaction input must be smaller than 3 MB. Split the file into a smaller business history.',
    );
}

function csvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [],
    field = '',
    quoted = false,
    closedQuote = false;
  function finishField() {
    row.push(field);
    field = '';
    closedQuote = false;
  }
  function finishRow() {
    finishField();
    if (row.some((value) => value.trim())) rows.push(row);
    row = [];
    if (rows.length > MAX_TRANSACTIONS + 1)
      throw new ImportError('CSV contains more than 20,000 transactions.');
  }
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          quoted = false;
          closedQuote = true;
        }
      } else field += char;
      continue;
    }
    if (char === ',') finishField();
    else if (char === '\n' || char === '\r') {
      if (char === '\r' && text[i + 1] === '\n') i++;
      finishRow();
    } else if (char === '"') {
      if (field.trim() || closedQuote)
        throw new ImportError(
          `CSV row ${rows.length + 1} contains an unexpected quote.`,
        );
      field = '';
      quoted = true;
    } else if (closedQuote && char.trim())
      throw new ImportError(
        `CSV row ${rows.length + 1} has text after a closing quote.`,
      );
    else field += char;
  }
  if (quoted)
    throw new ImportError(
      `CSV row ${rows.length + 1} has an unclosed quoted field.`,
    );
  if (field || row.length) finishRow();
  return rows;
}

function validateTransactions(records: unknown[]): ImportTransaction[] {
  if (!records.length)
    throw new ImportError('Provide at least one transaction.');
  if (records.length > MAX_TRANSACTIONS)
    throw new ImportError('Provide no more than 20,000 transactions.');
  return records.map((record, index) => {
    if (!record || typeof record !== 'object' || Array.isArray(record))
      throw new ImportError(`Transaction ${index + 1} must be an object.`);
    const item = record as Record<string, unknown>;
    if ('amount_index' in item)
      throw new ImportError(
        `Transaction ${index + 1} uses a legacy amount_index. New imports require actual UZS values in the amount field; indexed amounts cannot be relabeled as currency.`,
      );
    const unknown = Object.keys(item).filter((key) => !columns.includes(key));
    if (unknown.length)
      throw new ImportError(
        `Transaction ${index + 1}: unexpected field ${unknown.join(', ')}. Use only ts, direction, channel, amount.`,
      );
    const parsed = UserTransactionSchema.safeParse(item);
    if (!parsed.success)
      throw new ImportError(
        parsed.error.issues
          .slice(0, 3)
          .map(
            (issue) =>
              `Transaction ${index + 1}, ${issue.path.join('.')}: ${issue.message}`,
          )
          .join(' · '),
      );
    return parsed.data;
  });
}

export function parseTransactionInput(
  text: string,
  format: ImportFormat,
): {
  transactions: ImportTransaction[];
  profile?: { name?: string; sector?: string; location?: string };
} {
  checkSize(text);
  if (!text.trim())
    throw new ImportError(
      'Paste transaction data or upload a JSON or CSV file.',
    );
  if (format === 'csv') {
    const rows = csvRows(text.replace(/^\uFEFF/, ''));
    const header =
      rows.shift()?.map((column) => column.trim().toLowerCase()) ?? [];
    if (
      header.includes('generator_version') ||
      (header.includes('data_source') &&
        rows.some(
          (row) =>
            row[header.indexOf('data_source')]?.trim().toLowerCase() ===
            'synthetic',
        ))
    )
      throw new ImportError(
        'This file contains generated showcase data. Use it for sandbox testing; bank workspaces accept actual business transactions only.',
      );
    if (
      header.length !== columns.length ||
      new Set(header).size !== header.length ||
      columns.some((column) => !header.includes(column))
    )
      throw new ImportError(
        'CSV header must contain exactly ts, direction, channel, amount. Amounts are UZS; do not use amount_index.',
      );
    const records = rows.map((row, index) => {
      if (row.length !== header.length)
        throw new ImportError(
          `CSV row ${index + 2}: expected ${header.length} columns, found ${row.length}.`,
        );
      const item = Object.fromEntries(
        header.map((key, column) => [key, row[column].trim()]),
      );
      if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(item.amount))
        throw new ImportError(
          `CSV row ${index + 2}: amount must be a plain positive number without currency symbols or thousands separators.`,
        );
      return { ...item, amount: Number(item.amount) };
    });
    return { transactions: validateTransactions(records) };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new ImportError(
      'Transaction JSON is invalid. Use a JSON array or a business object containing transactions.',
    );
  }
  if (Array.isArray(parsed))
    return { transactions: validateTransactions(parsed) };
  if (!parsed || typeof parsed !== 'object' || !('transactions' in parsed))
    throw new ImportError(
      'JSON must be an array of transactions or an object with a transactions array.',
    );
  const object = parsed as Record<string, unknown>;
  if (
    object.data_source === 'synthetic' ||
    object.showcase_provenance !== undefined
  )
    throw new ImportError(
      'This file contains generated showcase data. Use it for sandbox testing; bank workspaces accept actual business transactions only.',
    );
  const unknown = Object.keys(object).filter(
    (key) =>
      ![
        'name',
        'sector',
        'location',
        'data_source',
        'amount_unit',
        'transactions',
      ].includes(key),
  );
  if (unknown.length)
    throw new ImportError(`Unexpected business fields: ${unknown.join(', ')}.`);
  if (
    (object.data_source !== undefined &&
      object.data_source !== 'user_provided') ||
    (object.amount_unit !== undefined && object.amount_unit !== 'UZS')
  )
    throw new ImportError(
      'This export uses legacy indexed or synthetic data. New imports require user-provided transaction amounts in UZS.',
    );
  if (!Array.isArray(object.transactions))
    throw new ImportError('The transactions field must be an array.');
  const profile: { name?: string; sector?: string; location?: string } = {};
  for (const key of ['name', 'sector', 'location'] as const) {
    if (object[key] !== undefined && typeof object[key] !== 'string')
      throw new ImportError(`Business ${key} must be a string.`);
    if (typeof object[key] === 'string') profile[key] = object[key];
  }
  return { transactions: validateTransactions(object.transactions), profile };
}

export function prepareBusinessImport(
  profile: { name: string; sector: string; location: string },
  text: string,
  format: ImportFormat,
): BusinessImport {
  const parsed = parseTransactionInput(text, format);
  const result = BusinessImportSchema.safeParse({
    ...profile,
    data_source: 'user_provided',
    amount_unit: 'UZS',
    transactions: parsed.transactions,
  });
  if (!result.success)
    throw new ImportError(
      result.error.issues
        .slice(0, 4)
        .map((issue) => `${issue.path.join('.')}: ${issue.message}`)
        .join(' · '),
    );
  checkSize(JSON.stringify(result.data));
  return result.data;
}
