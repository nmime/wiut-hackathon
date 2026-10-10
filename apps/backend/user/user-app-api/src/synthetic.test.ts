import { test } from 'node:test';
import assert from 'node:assert/strict';
import { BusinessDetailSchema, ScoreRequestSchema } from '@wiut/contracts';
import {
  businessDetail,
  generateSyntheticBusinesses,
  monthlyCashflow,
} from './synthetic.js';

test('all six synthetic histories are deterministic, valid and anchored to the documented period', () => {
  const businesses = generateSyntheticBusinesses();
  assert.deepEqual(businesses, generateSyntheticBusinesses());
  assert.equal(businesses.length, 6);
  assert.equal(new Set(businesses.map((business) => business.id)).size, 6);
  for (const business of businesses) {
    const detail = BusinessDetailSchema.parse(businessDetail(business));
    assert.equal(detail.data_source, 'synthetic');
    assert.equal(detail.last_activity_date, '2026-09-27');
    assert.equal(detail.latest_assessment, null);
    assert.equal(
      detail.history_months,
      business.id === 'synthetic-florist' ? 4 : 12,
    );
    assert.equal(detail.transaction_count, detail.history_months * 24);
    ScoreRequestSchema.parse({
      business_id: business.id,
      requested_amount: null,
      currency: 'UZS',
      as_of_date: '2026-09-30',
      transactions: business.transactions,
    });
  }
  assert.equal(businessDetail(businesses[2]!).trend, 'growing');
  assert.equal(businessDetail(businesses[3]!).trend, 'declining');
});

test('calendar months without transactions count as zero observed cash flow', () => {
  const months = monthlyCashflow([
    {
      ts: '2026-01-01T12:00:00Z',
      direction: 'in',
      channel: 'qr',
      amount_index: 10.15,
    },
    {
      ts: '2026-01-02T12:00:00Z',
      direction: 'out',
      channel: 'transfer',
      amount_index: 3.05,
    },
    {
      ts: '2026-03-01T12:00:00Z',
      direction: 'in',
      channel: 'card',
      amount_index: 4,
    },
  ]);
  assert.deepEqual(months, [
    {
      month: '2026-01',
      inflow_index: 10.15,
      outflow_index: 3.05,
      surplus_index: 7.1,
    },
    { month: '2026-02', inflow_index: 0, outflow_index: 0, surplus_index: 0 },
    { month: '2026-03', inflow_index: 4, outflow_index: 0, surplus_index: 4 },
  ]);
});

test('calendar aggregation stops at the end of the supported four-digit year range', () => {
  assert.deepEqual(
    monthlyCashflow([
      {
        ts: '9999-12-01T12:00:00Z',
        direction: 'in',
        channel: 'qr',
        amount_index: 10,
      },
    ]),
    [
      {
        month: '9999-12',
        inflow_index: 10,
        outflow_index: 0,
        surplus_index: 10,
      },
    ],
  );
});
