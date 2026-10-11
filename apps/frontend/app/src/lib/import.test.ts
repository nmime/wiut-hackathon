import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  MAX_IMPORT_BYTES,
  parseTransactionInput,
  prepareBusinessImport,
} from './import.ts';
import { amountLabel, businessExport, transactionCsv } from './format.ts';
import type { BusinessDetail } from '@wiut/contracts';

// Deliberately fabricated records exercise parsing only; these are never product seeds.
const transaction = {
  ts: '2026-09-01T10:00:00Z',
  direction: 'in',
  channel: 'card',
  amount: 1250000.5,
};
const profile = {
  name: 'Parser fixture',
  sector: 'Retail',
  location: 'Tashkent',
};
const csv =
  'ts,direction,channel,amount\n2026-09-01T10:00:00Z,in,card,1250000.5';

test('JSON array and business exports preserve actual UZS amounts', () => {
  assert.deepEqual(
    parseTransactionInput(JSON.stringify([transaction]), 'json').transactions,
    [transaction],
  );
  const result = prepareBusinessImport(
    profile,
    JSON.stringify({
      ...profile,
      data_source: 'user_provided',
      amount_unit: 'UZS',
      transactions: [transaction],
    }),
    'json',
  );
  assert.equal(result.amount_unit, 'UZS');
  assert.equal(result.data_source, 'user_provided');
  assert.deepEqual(result.transactions, [transaction]);
});

test('CSV handles reordered headers, UTF-8 BOM, quoted fields and CRLF', () => {
  const text =
    '\uFEFFamount,channel,direction,ts\r\n"1250000.5","card",in,"2026-09-01T10:00:00Z"\r\n\r\n';
  assert.deepEqual(parseTransactionInput(text, 'csv').transactions, [
    transaction,
  ]);
  assert.deepEqual(prepareBusinessImport(profile, csv, 'csv').transactions, [
    transaction,
  ]);
});

test('JSON files can provide the profile while the form remains authoritative', () => {
  const text = JSON.stringify({ ...profile, transactions: [transaction] });
  assert.deepEqual(parseTransactionInput(text, 'json').profile, profile);
  assert.equal(
    prepareBusinessImport(
      { ...profile, name: 'Changed by officer' },
      text,
      'json',
    ).name,
    'Changed by officer',
  );
});

test('legacy indexed and synthetic exports cannot be relabeled UZS', () => {
  assert.throws(
    () =>
      parseTransactionInput(
        JSON.stringify([{ ...transaction, amount_index: 100 }]),
        'json',
      ),
    /legacy amount_index/,
  );
  for (const metadata of [
    { amount_unit: 'index' },
    { data_source: 'synthetic' },
  ]) {
    assert.throws(
      () =>
        parseTransactionInput(
          JSON.stringify({
            ...profile,
            ...metadata,
            transactions: [transaction],
          }),
          'json',
        ),
      /legacy indexed or synthetic|generated showcase data/,
    );
  }
  assert.throws(
    () =>
      parseTransactionInput(csv.replace('amount\n', 'amount_index\n'), 'csv'),
    /CSV header/,
  );
});

test('CSV rejects ambiguous numbers, duplicate or missing columns and row widths', () => {
  for (const amount of ['1 250', 'UZS 100', 'NaN', 'Infinity', '0x10', '']) {
    assert.throws(
      () => parseTransactionInput(csv.replace('1250000.5', amount), 'csv'),
      /plain positive number/,
    );
  }
  assert.throws(
    () => parseTransactionInput(csv.replace('amount\n', 'direction\n'), 'csv'),
    /CSV header/,
  );
  assert.throws(
    () => parseTransactionInput(csv + ',extra', 'csv'),
    /CSV row 2: expected 4 columns, found 5/,
  );
  assert.throws(
    () =>
      parseTransactionInput(
        'ts,direction,channel\n2026-09-01T10:00:00Z,in,card',
        'csv',
      ),
    /CSV header/,
  );
});

test('malformed quotes produce useful CSV row errors', () => {
  assert.throws(
    () => parseTransactionInput(csv.replace('1250000.5', '"1250000.5'), 'csv'),
    /row 2 has an unclosed/,
  );
  assert.throws(
    () =>
      parseTransactionInput(
        csv.replace('1250000.5', '"1250000.5"extra'),
        'csv',
      ),
    /row 2 has text after/,
  );
  assert.throws(
    () => parseTransactionInput(csv.replace('1250000.5', '12"50'), 'csv'),
    /row 2 contains an unexpected quote/,
  );
});

test('shared schema rejects invalid dates, directions, channels and amount ranges', () => {
  for (const change of [
    { ts: '2026-02-30T10:00:00Z' },
    { direction: 'incoming' },
    { channel: 'bank' },
    { amount: 0 },
    { amount: -1 },
    { amount: 1e12 + 1 },
    { amount: '100' },
  ]) {
    assert.throws(
      () =>
        parseTransactionInput(
          JSON.stringify([{ ...transaction, ...change }]),
          'json',
        ),
      /Transaction 1/,
    );
  }
  assert.throws(
    () =>
      parseTransactionInput(
        JSON.stringify([{ ...transaction, account_number: 'not-allowed' }]),
        'json',
      ),
    /unexpected field account_number/,
  );
});

test('empty, malformed and oversized data are bounded before submission', () => {
  assert.throws(
    () => parseTransactionInput('', 'json'),
    /Paste transaction data/,
  );
  assert.throws(() => parseTransactionInput('{', 'json'), /JSON is invalid/);
  assert.throws(() => parseTransactionInput('[]', 'json'), /at least one/);
  assert.throws(
    () => parseTransactionInput(JSON.stringify({ transactions: {} }), 'json'),
    /must be an array/,
  );
  assert.throws(
    () => parseTransactionInput(' '.repeat(MAX_IMPORT_BYTES + 1), 'json'),
    /smaller than 3 MB/,
  );
  assert.throws(
    () => parseTransactionInput('я'.repeat(MAX_IMPORT_BYTES / 2 + 1), 'json'),
    /smaller than 3 MB/,
  );
  assert.throws(
    () =>
      parseTransactionInput(
        JSON.stringify(Array(20001).fill(transaction)),
        'json',
      ),
    /no more than 20,000/,
  );
  assert.throws(
    () =>
      parseTransactionInput(
        'ts,direction,channel,amount\n' +
          '2026-09-01T10:00:00Z,in,card,1\n'.repeat(20001),
        'csv',
      ),
    /more than 20,000/,
  );
});

test('bad business metadata and short profile fields cannot reach the API', () => {
  assert.throws(
    () =>
      parseTransactionInput(
        JSON.stringify({
          ...profile,
          unknown: true,
          transactions: [transaction],
        }),
        'json',
      ),
    /Unexpected business fields/,
  );
  assert.throws(
    () =>
      parseTransactionInput(
        JSON.stringify({ ...profile, name: 7, transactions: [transaction] }),
        'json',
      ),
    /Business name must be a string/,
  );
  assert.throws(
    () => prepareBusinessImport({ ...profile, name: 'x' }, csv, 'csv'),
    /name:/,
  );
});

test('currency export round-trips while legacy export stays explicitly indexed', () => {
  const details = {
    ...profile,
    id: 'format-fixture',
    data_source: 'user_provided',
    amount_unit: 'UZS',
    transactions: [
      {
        ts: transaction.ts,
        direction: 'in',
        channel: 'card',
        amount_index: transaction.amount,
      },
    ],
  } as BusinessDetail;
  const exported = businessExport(details);
  assert.deepEqual(
    prepareBusinessImport(profile, JSON.stringify(exported), 'json')
      .transactions,
    [transaction],
  );
  assert.equal(amountLabel(transaction.amount, 'UZS'), '1,250,000.5 UZS');
  const legacy = businessExport({
    ...details,
    data_source: 'synthetic',
    amount_unit: 'index',
  });
  assert.equal(legacy.amount_unit, 'index');
  assert.ok('amount_index' in legacy.transactions[0]);
  assert.equal(legacy.transactions[0].amount_index, transaction.amount);
  assert.equal('amount' in legacy.transactions[0], false);
  assert.equal(amountLabel(123, 'index'), '123 idx');
});

test('showcase exports preserve synthetic provenance and cannot enter bank imports', () => {
  const showcase = {
    ...profile,
    id: 'showcase-format-fixture',
    data_source: 'synthetic',
    amount_unit: 'UZS',
    showcase_provenance: {
      generator_version: 'showcase-v1',
      seed: 7261,
      scenario: 'stable',
      months: 24,
      end_month: '2026-09',
      monthly_revenue_uzs: 30000000,
      batch_index: 0,
    },
    transactions: [{ ...transaction, amount_index: transaction.amount }],
  } as unknown as BusinessDetail;
  const exported = businessExport(showcase);
  assert.equal(exported.data_source, 'synthetic');
  assert.deepEqual(exported.showcase_provenance, showcase.showcase_provenance);
  assert.ok('amount' in exported.transactions[0]);
  assert.equal(exported.transactions[0].amount, transaction.amount);
  assert.throws(
    () => prepareBusinessImport(profile, JSON.stringify(exported), 'json'),
    /generated showcase data/,
  );
  const exportedCsv = transactionCsv(showcase);
  assert.match(
    exportedCsv,
    /^data_source,amount_unit,generator_version,seed,scenario,/,
  );
  assert.match(
    exportedCsv,
    /synthetic,UZS,showcase-v1,7261,stable,24,2026-09,30000000,0,/,
  );
  assert.throws(
    () => prepareBusinessImport(profile, exportedCsv, 'csv'),
    /generated showcase data/,
  );
  assert.throws(
    () =>
      parseTransactionInput(
        exportedCsv.replace('synthetic,UZS', 'user_provided,UZS'),
        'csv',
      ),
    /generated showcase data/,
  );
  assert.throws(
    () =>
      parseTransactionInput(
        `data_source,${csv.replace('\n', '\nsynthetic,')}`,
        'csv',
      ),
    /generated showcase data/,
  );
});

test('actual transaction CSV export keeps its declared UZS import format', () => {
  const business = {
    ...profile,
    data_source: 'user_provided',
    amount_unit: 'UZS',
    showcase_provenance: null,
    transactions: [
      {
        ts: transaction.ts,
        direction: transaction.direction,
        channel: transaction.channel,
        amount_index: transaction.amount,
      },
    ],
  } as BusinessDetail;
  assert.equal(transactionCsv(business), csv);
  assert.deepEqual(
    prepareBusinessImport(profile, transactionCsv(business), 'csv')
      .transactions,
    [transaction],
  );
});
