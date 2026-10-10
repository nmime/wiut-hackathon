import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DecisionInputSchema } from '@wiut/contracts';
import type { Assessment } from '@wiut/contracts';
import { loadConfig } from './config.js';
import { type Database } from './database.js';
import { type MlClient } from './ml.js';
import { ApiProblem, validate } from './problem.js';
import { inputHash, ProductService } from './service.js';
import { generateSyntheticBusinesses } from './synthetic.js';

test('portfolio summaries use one batch lookup while preserving each business latest assessment', async () => {
  const businesses = generateSyntheticBusinesses();
  const attempt: Assessment = {
    id: 'ea7f3623-d512-4b51-8653-e6b9be38dd09',
    business_id: businesses[0]!.id,
    requested_amount: null,
    as_of_date: '2026-09-27',
    status: 'failed',
    created_at: '2026-10-10T15:00:00.000Z',
    request_id: 'test-only-failed-attempt',
    input_hash: 'a'.repeat(64),
    result: null,
    error: 'Test-only unavailable ML attempt.',
    decision: null,
  };
  let batchCalls = 0;
  const database = {
    businesses: async () => businesses,
    latestAssessments: async (ids: string[]) => {
      batchCalls++;
      assert.deepEqual(
        ids,
        businesses.map((business) => business.id),
      );
      return new Map([[attempt.business_id, attempt]]);
    },
    latestAssessment: async () => {
      assert.fail(
        'Portfolio must not query latest assessments one business at a time',
      );
    },
  } as unknown as Database;
  const result = await new ProductService(
    database,
    {} as MlClient,
    loadConfig({}),
  ).businesses();
  assert.equal(batchCalls, 1);
  assert.equal(result.synthetic, true);
  assert.deepEqual(result.items[0]!.latest_assessment, attempt);
  assert.ok(
    result.items
      .slice(1)
      .every((business) => business.latest_assessment === null),
  );
  assert.ok(
    result.items.every(
      (business) =>
        !('transactions' in business) && !('monthly_cashflow' in business),
    ),
  );
});

test('ML failure is preceded by durable attempt creation and followed by durable failure', async () => {
  const events: string[] = [];
  const database = {
    business: async () => generateSyntheticBusinesses()[0],
    beginAssessment: async (
      _id: string,
      input: { transactions: Array<{ ts: string }> },
    ) => {
      assert.ok(
        input.transactions.every(
          (transaction) => transaction.ts.slice(0, 10) <= '2026-01-01',
        ),
      );
      events.push('persist_attempt');
    },
    finishAssessment: async (
      _id: string,
      result: unknown,
      error: string,
      status: number,
    ) => {
      assert.equal(result, null);
      assert.equal(error, 'ML unavailable');
      assert.equal(status, 503);
      events.push('persist_failure');
    },
  } as unknown as Database;
  const ml = {
    score: async () => {
      events.push('call_ml');
      throw new ApiProblem(503, 'Unavailable', 'ML unavailable');
    },
  } as unknown as MlClient;
  await assert.rejects(
    new ProductService(database, ml, loadConfig({})).createAssessment(
      {
        business_id: 'synthetic-bakery',
        as_of_date: '2026-01-01',
        requested_amount: null,
      },
      'test-request',
    ),
    (error: unknown) => error instanceof ApiProblem && error.status === 503,
  );
  assert.deepEqual(events, ['persist_attempt', 'call_ml', 'persist_failure']);
});

test('invalid assessment requests for a known business are audited without calling ML', async () => {
  let audits = 0;
  const database = {
    business: async () => generateSyntheticBusinesses()[0],
    audit: async (event: {
      event_type: string;
      metadata: { input_hash: string };
    }) => {
      assert.equal(event.event_type, 'assessment_rejected');
      assert.match(event.metadata.input_hash, /^[a-f0-9]{64}$/);
      audits++;
    },
  } as unknown as Database;
  const ml = {
    score: async () => {
      assert.fail('Rejected assessment must not invoke ML');
    },
  } as unknown as MlClient;
  const service = new ProductService(database, ml, loadConfig({}));
  await assert.rejects(
    service.createAssessment(
      { business_id: 'synthetic-bakery', as_of_date: '2026-02-31' },
      'test-request',
    ),
    (error: unknown) => error instanceof ApiProblem && error.status === 400,
  );
  await assert.rejects(
    service.createAssessment(
      { business_id: 'synthetic-bakery', as_of_date: '2025-01-01' },
      'test-request',
    ),
    (error: unknown) => error instanceof ApiProblem && error.status === 400,
  );
  assert.equal(audits, 2);
});

test('human decisions require reviewer identity and substantive notes, with strict fields', () => {
  assert.deepEqual(
    validate(DecisionInputSchema, {
      decision: 'approved',
      reviewer_name: '  Reviewer  ',
      notes: '  Reviewed synthetic cash flow.  ',
    }),
    {
      decision: 'approved',
      reviewer_name: 'Reviewer',
      notes: 'Reviewed synthetic cash flow.',
    },
  );
  for (const input of [
    {
      decision: 'approved',
      reviewer_name: 'R',
      notes: 'Reviewed synthetic cash flow.',
    },
    { decision: 'approved', reviewer_name: 'Reviewer', notes: 'yes' },
    {
      decision: 'approved',
      reviewer_name: 'Reviewer',
      notes: 'Reviewed synthetic cash flow.',
      automatic: true,
    },
  ])
    assert.throws(() => validate(DecisionInputSchema, input), ApiProblem);
});

test('a rejected duplicate human decision keeps its reviewer and validated submission in the audit', async () => {
  const submission = {
    decision: 'declined' as const,
    reviewer_name: 'Second reviewer',
    notes: 'Reviewed the synthetic transaction history.',
  };
  let audited = false;
  const database = {
    assessmentBusinessId: async () => 'synthetic-bakery',
    recordDecision: async () => {
      throw new ApiProblem(
        409,
        'Already reviewed',
        'A human decision already exists.',
      );
    },
    audit: async (event: {
      actor: string;
      metadata: { submission: unknown };
      event_type: string;
    }) => {
      assert.equal(event.actor, submission.reviewer_name);
      assert.deepEqual(event.metadata.submission, submission);
      assert.equal(event.event_type, 'decision_rejected');
      audited = true;
    },
  } as unknown as Database;
  await assert.rejects(
    new ProductService(database, {} as MlClient, loadConfig({})).decide(
      'assessment-id',
      submission,
      'test-request',
    ),
    (error: unknown) => error instanceof ApiProblem && error.status === 409,
  );
  assert.equal(audited, true);
});

test('audit hashes use SHA-256 and change when inputs change', () => {
  assert.match(
    inputHash({ business_id: 'synthetic-bakery' }),
    /^[a-f0-9]{64}$/,
  );
  assert.equal(
    inputHash({ business_id: 'synthetic-bakery' }),
    inputHash({ business_id: 'synthetic-bakery' }),
  );
  assert.notEqual(
    inputHash({ business_id: 'synthetic-bakery' }),
    inputHash({ business_id: 'synthetic-textile' }),
  );
});
