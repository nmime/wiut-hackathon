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
import type { AuthContext } from './auth-types.js';
const auth: AuthContext = {
  user: {
    id: '11111111-1111-4111-8111-111111111111',
    email: 'officer@example.test',
    display_name: 'Authenticated officer',
  },
  tenant: {
    id: '22222222-2222-4222-8222-222222222222',
    name: 'Test bank',
    role: 'officer',
  },
  tenants: [],
  csrf_token: 'a'.repeat(43),
  session_hash: 'test-session',
};

test('portfolio summaries use one batch lookup while preserving each business latest assessment', async () => {
  const businesses = generateSyntheticBusinesses();
  const attempt: Assessment = {
    id: 'ea7f3623-d512-4b51-8653-e6b9be38dd09',
    business_id: businesses[0]!.id,
    amount_unit: 'index',
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
  ).businesses(auth);
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
      tenantId: string,
      status: number,
    ) => {
      assert.equal(result, null);
      assert.equal(error, 'ML unavailable');
      assert.equal(status, 503);
      assert.equal(tenantId, auth.tenant.id);
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
      auth,
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
      auth,
    ),
    (error: unknown) => error instanceof ApiProblem && error.status === 400,
  );
  await assert.rejects(
    service.createAssessment(
      { business_id: 'synthetic-bakery', as_of_date: '2025-01-01' },
      'test-request',
      auth,
    ),
    (error: unknown) => error instanceof ApiProblem && error.status === 400,
  );
  assert.equal(audits, 2);
});

test('human decisions accept optional deprecated reviewer field and require substantive notes, with strict fields', () => {
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
  assert.deepEqual(
    validate(DecisionInputSchema, {
      decision: 'approved',
      notes: 'Reviewed synthetic cash flow.',
    }),
    { decision: 'approved', notes: 'Reviewed synthetic cash flow.' },
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

test('a rejected duplicate human decision uses authenticated reviewer rather than a forged submission', async () => {
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
      assert.equal(event.actor, auth.user.display_name);
      assert.deepEqual(event.metadata.submission, {
        ...submission,
        reviewer_name: auth.user.display_name,
      });
      assert.equal(event.event_type, 'decision_rejected');
      audited = true;
    },
  } as unknown as Database;
  await assert.rejects(
    new ProductService(database, {} as MlClient, loadConfig({})).decide(
      'assessment-id',
      submission,
      'test-request',
      auth,
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

test('user-provided UZS amounts preserve exact 1:1 internal values and declared units', async () => {
  let imported = false;
  const database = {
    importBusiness: async (
      business: import('./business.js').StoredBusiness,
      _requestId: string,
      context: AuthContext,
    ) => {
      imported = true;
      assert.equal(context.user.id, auth.user.id);
      assert.equal(business.data_source, 'user_provided');
      assert.equal(business.amount_unit, 'UZS');
      assert.equal(business.archived_at, null);
      assert.equal(business.transactions[0]!.amount_index, 1000000.75);
      assert.equal('amount' in business.transactions[0]!, false);
    },
  } as unknown as Database;
  const result = await new ProductService(
    database,
    {} as MlClient,
    loadConfig({ NODE_ENV: 'production' }),
  ).importBusiness(
    {
      name: 'Uploaded business',
      sector: 'Retail',
      location: 'Tashkent',
      transactions: [
        {
          ts: '2026-09-01T12:00:00Z',
          direction: 'in',
          channel: 'card',
          amount: 1000000.75,
        },
      ],
    },
    'test-upload',
    auth,
  );
  assert.equal(imported, true);
  assert.equal(result.amount_unit, 'UZS');
  assert.equal(result.data_source, 'user_provided');
  assert.equal(result.avg_monthly_inflow_index, 1000000.75);
});

test('production rejects new synthetic imports while explicit test mode permits legacy fixtures', async () => {
  const input = {
    name: 'Test fixture',
    sector: 'Retail',
    location: 'Tashkent',
    data_source: 'synthetic',
    transactions: [
      {
        ts: '2026-09-01T12:00:00Z',
        direction: 'in',
        channel: 'card',
        amount_index: 10,
      },
    ],
  };
  let calls = 0;
  const database = {
    importBusiness: async () => {
      calls++;
    },
  } as unknown as Database;
  await assert.rejects(
    new ProductService(
      database,
      {} as MlClient,
      loadConfig({ NODE_ENV: 'production' }),
    ).importBusiness(input, 'test-upload', auth),
    (error: unknown) => error instanceof ApiProblem && error.status === 400,
  );
  assert.equal(calls, 0);
  const response = await new ProductService(
    database,
    {} as MlClient,
    loadConfig({ NODE_ENV: 'test' }),
  ).importBusiness(input, 'test-upload', auth);
  assert.equal(calls, 1);
  assert.equal(response.data_source, 'synthetic');
  assert.equal(response.amount_unit, 'index');
});

test('an empty portfolio contains no automatically generated businesses or synthetic label', async () => {
  const database = {
    businesses: async () => [],
    latestAssessments: async () => new Map(),
  } as unknown as Database;
  const response = await new ProductService(
    database,
    {} as MlClient,
    loadConfig({}),
  ).businesses(auth);
  assert.deepEqual(response, { items: [], synthetic: false });
});

test('archived businesses retain historical access but new assessment rejection is audited', async () => {
  const business = {
    ...generateSyntheticBusinesses()[0]!,
    archived_at: new Date('2026-10-10T00:00:00Z'),
  };
  let rejected = false;
  const database = {
    business: async () => business,
    audit: async (event: {
      event_type: string;
      metadata: { status: number };
    }) => {
      assert.equal(event.event_type, 'assessment_rejected');
      assert.equal(event.metadata.status, 409);
      rejected = true;
    },
    beginAssessment: async () =>
      assert.fail('Archived business must not create an ML attempt'),
  } as unknown as Database;
  const service = new ProductService(database, {} as MlClient, loadConfig({}));
  await assert.rejects(
    service.createAssessment(
      { business_id: business.id, as_of_date: '2026-09-27' },
      'test-archive',
      auth,
    ),
    (error: unknown) => error instanceof ApiProblem && error.status === 409,
  );
  assert.equal(rejected, true);
});
