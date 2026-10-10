import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  AssessmentSchema,
  BusinessImportSchema,
  DecisionInputSchema,
  ScoreRequestSchema,
  ScoreResponseSchema,
  TransactionSchema,
} from './index.js';

test('transaction input rejects invalid dates, negative amounts and unknown fields', () => {
  const transaction = {
    ts: '2026-10-01T12:00:00',
    direction: 'in',
    channel: 'qr',
    amount_index: 50,
  };
  assert.equal(TransactionSchema.safeParse(transaction).success, true);
  assert.equal(
    TransactionSchema.safeParse({ ...transaction, ts: '2026-99-01T12:00:00' })
      .success,
    false,
  );
  assert.equal(
    TransactionSchema.safeParse({ ...transaction, ts: '2026-02-31T12:00:00' })
      .success,
    false,
  );
  assert.equal(
    TransactionSchema.safeParse({ ...transaction, ts: '2026-10-01T24:00:00' })
      .success,
    false,
  );
  assert.equal(
    TransactionSchema.safeParse({ ...transaction, ts: '0000-10-01T12:00:00' })
      .success,
    false,
  );
  assert.equal(
    TransactionSchema.safeParse({ ...transaction, amount_index: -1 }).success,
    false,
  );
  assert.equal(
    TransactionSchema.safeParse({ ...transaction, customer_name: 'private' })
      .success,
    false,
  );
});

test('score input enforces a historical cutoff and synthetic import declaration', () => {
  const transactions = [
    {
      ts: '2026-10-09T12:00:00Z',
      direction: 'in',
      channel: 'card',
      amount_index: 25,
    },
  ];
  assert.equal(
    ScoreRequestSchema.safeParse({
      business_id: 'demo',
      as_of_date: '2026-10-10',
      transactions,
    }).success,
    true,
  );
  assert.equal(
    ScoreRequestSchema.safeParse({
      business_id: 'demo',
      as_of_date: '2026-10-01',
      transactions,
    }).success,
    false,
  );
  assert.equal(
    BusinessImportSchema.safeParse({
      name: 'Sample',
      sector: 'Retail',
      location: 'Tashkent',
      data_source: 'real',
      transactions,
    }).success,
    false,
  );
});

test('human decisions require a reviewer and substantive notes', () => {
  assert.equal(
    DecisionInputSchema.safeParse({
      decision: 'approved',
      reviewer_name: 'Officer',
      notes: 'Reviewed cash flow.',
    }).success,
    true,
  );
  assert.equal(
    DecisionInputSchema.safeParse({
      decision: 'approved',
      reviewer_name: ' ',
      notes: 'ok',
    }).success,
    false,
  );
});

test('ML contract rejects impossible confidence and incoherent payment schedules', () => {
  const response = {
    business_id: 'demo',
    as_of_date: '2026-10-10',
    capacity_score: 60,
    score_band: 'medium',
    cashflow_summary: {
      avg_monthly_inflow_index: 100,
      inflow_volatility: 0.2,
      net_monthly_surplus_index: 30,
      trend: 'stable',
    },
    recommended_loan: {
      max_affordable_installment_index: 15,
      suggested_principal_index: 120,
      suggested_term_months: 12,
      rationale: 'Test fixture',
    },
    seasonality: {
      monthly_forecast_index: Array(12).fill(30),
      weak_months: [1],
      strong_months: [8],
    },
    adaptive_schedule: Array.from({ length: 12 }, (_, i) => ({
      month_offset: i + 1,
      installment_index: 10,
      note: 'normal',
    })),
    explanation: { top_factors: [], advisory: [] },
    confidence: 0.8,
    flags: [],
    model_version: 'test',
    request_id: 'test',
  };
  assert.equal(ScoreResponseSchema.safeParse(response).success, true);
  assert.equal(
    ScoreResponseSchema.safeParse({ ...response, confidence: 80 }).success,
    false,
  );
  assert.equal(
    ScoreResponseSchema.safeParse({ ...response, adaptive_schedule: [] })
      .success,
    false,
  );
  assert.equal(
    ScoreResponseSchema.safeParse({
      ...response,
      seasonality: { ...response.seasonality, strong_months: [1] },
    }).success,
    false,
  );
  const assessment = {
    id: 'assessment-test',
    business_id: 'demo',
    requested_amount: null,
    as_of_date: '2026-10-10',
    status: 'completed',
    created_at: '2026-10-10T00:00:00Z',
    request_id: 'api-test',
    input_hash: 'hash',
    result: response,
    error: null,
    decision: null,
  };
  assert.equal(AssessmentSchema.safeParse(assessment).success, true);
  assert.equal(
    AssessmentSchema.safeParse({
      ...assessment,
      status: 'failed',
      error: 'offline',
    }).success,
    false,
  );
  assert.equal(
    AssessmentSchema.safeParse({ ...assessment, result: null }).success,
    false,
  );
  assert.equal(
    AssessmentSchema.safeParse({
      ...assessment,
      business_id: 'different-business',
    }).success,
    false,
  );
  assert.equal(
    AssessmentSchema.safeParse({
      ...assessment,
      decision: {
        id: 'decision-test',
        assessment_id: 'different-assessment',
        decision: 'approved',
        reviewer_name: 'Officer',
        notes: 'Checked the cash flow.',
        created_at: '2026-10-10T00:00:00Z',
      },
    }).success,
    false,
  );
});
