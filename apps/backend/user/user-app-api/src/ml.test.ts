import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ScoreResponseSchema,
  type ScoreRequest,
  type ScoreResponse,
} from '@wiut/contracts';
import { MAX_ML_ERROR_BYTES, MAX_ML_RESPONSE_BYTES, MlClient } from './ml.js';
import { ApiProblem } from './problem.js';

const request: ScoreRequest = {
  business_id: 'test-only-business',
  requested_amount: null,
  currency: 'UZS',
  as_of_date: '2026-09-30',
  transactions: [
    {
      ts: '2026-09-01T12:00:00Z',
      direction: 'in',
      channel: 'qr',
      amount_index: 100,
    },
  ],
};
// This is a protocol fixture for adapter tests, never seeded or served as a model result.
const fixture: ScoreResponse = {
  business_id: request.business_id,
  as_of_date: request.as_of_date,
  capacity_score: 50,
  score_band: 'medium',
  cashflow_summary: {
    avg_monthly_inflow_index: 100,
    inflow_volatility: 0.1,
    net_monthly_surplus_index: 20,
    trend: 'stable',
  },
  recommended_loan: {
    max_affordable_installment_index: 10,
    suggested_principal_index: 120,
    suggested_term_months: 12,
    rationale: 'Test-only response for protocol validation.',
  },
  seasonality: {
    monthly_forecast_index: Array.from({ length: 12 }, () => 100),
    weak_months: [1],
    strong_months: [12],
  },
  adaptive_schedule: Array.from({ length: 12 }, (_, i) => ({
    month_offset: i + 1,
    installment_index: 10,
    note: 'normal' as const,
  })),
  explanation: {
    top_factors: [
      { factor: 'test-only fixture', impact: 'positive', weight: 1 },
    ],
    advisory: ['Test-only advice.'],
  },
  confidence: 0.5,
  flags: ['test-only'],
  model_version: 'test-only-fixture-v1',
  request_id: 'ml-test-request',
};
const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    headers: { 'content-type': 'application/json' },
  });
const status = (expected: number) => (error: unknown) =>
  error instanceof ApiProblem && error.status === expected;
const client = (fetcher: typeof fetch) =>
  new MlClient(
    { ML_SERVICE_URL: 'http://localhost:8000/v1/', ML_TIMEOUT_MS: 1000 },
    fetcher,
  );

test('adapter sends exact scoring request and validates returned payload', async () => {
  ScoreResponseSchema.parse(fixture);
  const ml = client(async (input, options) => {
    assert.equal(input, 'http://localhost:8000/v1/score');
    assert.equal(options?.method, 'POST');
    assert.deepEqual(JSON.parse(String(options?.body)), request);
    assert.equal(
      (options?.headers as Record<string, string>)['x-request-id'],
      'api-test-request',
    );
    return json(fixture);
  });
  assert.deepEqual(await ml.score(request, 'api-test-request'), fixture);
});

test('unconfigured and unreachable ML services report503 without inventing a result', async () => {
  await assert.rejects(
    new MlClient({ ML_SERVICE_URL: undefined, ML_TIMEOUT_MS: 100 }).score(
      request,
      'request',
    ),
    status(503),
  );
  await assert.rejects(
    client(async () => {
      throw new TypeError('private connection details');
    }).score(request, 'request'),
    (error: unknown) =>
      status(503)(error) && !(error as Error).message.includes('private'),
  );
});

test('malformed, non-JSON, wrong-business, wrong-date, and invalid scoring outputs report502', async () => {
  const responses = [
    new Response('upstream detail must not leak', { status: 422 }),
    new Response('{}', { headers: { 'content-type': 'text/html' } }),
    new Response('broken JSON', {
      headers: { 'content-type': 'application/json' },
    }),
    json({ ...fixture, business_id: 'another-business' }),
    json({ ...fixture, as_of_date: '2026-10-01' }),
    json({ ...fixture, capacity_score: 101 }),
    json({ ...fixture, confidence: -1 }),
    json({
      ...fixture,
      seasonality: {
        ...fixture.seasonality,
        weak_months: [1],
        strong_months: [1],
      },
    }),
    json({ ...fixture, adaptive_schedule: fixture.adaptive_schedule.slice(1) }),
  ];
  for (const response of responses)
    await assert.rejects(
      client(async () => response).score(request, 'request'),
      status(502),
    );
});

test('declared and streamed responses are bounded before schema parsing', async () => {
  await assert.rejects(
    client(
      async () =>
        new Response('{}', {
          headers: {
            'content-type': 'application/json',
            'content-length': String(MAX_ML_RESPONSE_BYTES + 1),
          },
        }),
    ).score(request, 'request'),
    status(502),
  );
  await assert.rejects(
    client(
      async () =>
        new Response('x'.repeat(MAX_ML_RESPONSE_BYTES + 1), {
          headers: { 'content-type': 'application/json' },
        }),
    ).score(request, 'request'),
    status(502),
  );
});

test('financially incoherent ML responses fail502 while a valid interest-bearing schedule is accepted', async () => {
  for (const invalid of [
    {
      ...fixture,
      adaptive_schedule: fixture.adaptive_schedule.map((row) => ({
        ...row,
        installment_index: 0,
      })),
    },
    {
      ...fixture,
      recommended_loan: {
        ...fixture.recommended_loan,
        suggested_principal_index: 0,
      },
    },
    {
      ...fixture,
      flags: ['zero_interest_mvp'],
      adaptive_schedule: fixture.adaptive_schedule.map((row) => ({
        ...row,
        installment_index: 11,
      })),
    },
  ]) {
    await assert.rejects(
      client(async () => json(invalid)).score(request, 'request'),
      status(502),
    );
  }
  const interestBearing = {
    ...fixture,
    adaptive_schedule: fixture.adaptive_schedule.map((row) => ({
      ...row,
      installment_index: 11,
    })),
  };
  assert.deepEqual(
    await client(async () => json(interestBearing)).score(request, 'request'),
    interestBearing,
  );
});

test('timeout aborts a slow upstream and reports504', async () => {
  const ml = new MlClient(
    { ML_SERVICE_URL: 'http://localhost:8000', ML_TIMEOUT_MS: 10 },
    async (_input, options) =>
      new Promise<Response>((_resolve, reject) => {
        options?.signal?.addEventListener(
          'abort',
          () => reject(new DOMException('Aborted', 'AbortError')),
          { once: true },
        );
      }),
  );
  await assert.rejects(ml.score(request, 'request'), status(504));
});

test('known candidate refusals retain a safe month-end explanation with HTTP502', async () => {
  const detail =
    'The teammate candidate requires a completed calendar month-end assessment date. Select the latest completed month-end or use the real-data blend.';
  await assert.rejects(
    client(
      async () =>
        new Response(JSON.stringify({ code: 'month_end_required', detail }), {
          status: 422,
          headers: {
            'content-type': 'application/problem+json; charset=utf-8',
          },
        }),
    ).score(request, 'request'),
    (error: unknown) =>
      error instanceof ApiProblem &&
      error.status === 502 &&
      error.detail.includes(detail) &&
      error.detail.includes('This attempt has been saved.'),
  );
  for (const code of [
    'insufficient_history',
    'unsupported_calendar',
    'invalid_input',
  ]) {
    await assert.rejects(
      client(
        async () =>
          new Response(
            JSON.stringify({ code, detail: 'Candidate refused this input.' }),
            {
              status: 422,
              headers: { 'content-type': 'application/json' },
            },
          ),
      ).score(request, 'request'),
      (error: unknown) =>
        status(502)(error) &&
        !(error as ApiProblem).detail.includes('Candidate refused this input.'),
    );
  }
});

test('malformed, unknown and unsafe upstream refusal diagnostics remain generic', async () => {
  for (const body of [
    'not JSON',
    JSON.stringify({ code: 'new_unsafe_code', detail: 'do not expose this' }),
    JSON.stringify({
      code: 'month_end_required',
      detail: 'Traceback /app/vendor/private.py password secret',
    }),
    JSON.stringify({
      code: 'month_end_required',
      detail: 'Error',
      stack: 'private diagnostic',
    }),
    JSON.stringify({
      code: 'month_end_required',
      detail: '<script>alert(1)</script>',
    }),
    JSON.stringify({ code: 'month_end_required', detail: 'x'.repeat(501) }),
    JSON.stringify({ code: 'month_end_required', detail: 42 }),
  ]) {
    await assert.rejects(
      client(
        async () =>
          new Response(body, {
            status: 422,
            headers: { 'content-type': 'application/json' },
          }),
      ).score(request, 'request'),
      (error: unknown) =>
        error instanceof ApiProblem &&
        error.status === 502 &&
        error.detail ===
          'The ML service returned HTTP 422. This attempt has been saved.',
    );
  }
});

test('declared and streamed error bodies stop at their smaller byte limit and cancel', async () => {
  for (const declared of [true, false]) {
    let canceled = false;
    let reads = 0;
    const stream = new ReadableStream<Uint8Array>(
      {
        pull(controller) {
          reads += 1;
          controller.enqueue(new Uint8Array(MAX_ML_ERROR_BYTES + 1));
        },
        cancel() {
          canceled = true;
        },
      },
      { highWaterMark: 0 },
    );
    await assert.rejects(
      client(
        async () =>
          new Response(stream, {
            status: 422,
            headers: {
              'content-type': 'application/json',
              ...(declared
                ? { 'content-length': String(MAX_ML_ERROR_BYTES + 1) }
                : {}),
            },
          }),
      ).score(request, 'request'),
      (error: unknown) =>
        error instanceof ApiProblem &&
        error.status === 502 &&
        !error.detail.includes('month-end'),
    );
    assert.equal(canceled, true);
    assert.equal(reads, declared ? 0 : 1);
  }
});

test('a stalled refusal body is canceled by the existing request timeout', async () => {
  let canceled = false;
  const stream = new ReadableStream<Uint8Array>(
    {
      cancel() {
        canceled = true;
      },
    },
    { highWaterMark: 0 },
  );
  const ml = new MlClient(
    { ML_SERVICE_URL: 'http://localhost:8000', ML_TIMEOUT_MS: 10 },
    async () =>
      new Response(stream, {
        status: 422,
        headers: { 'content-type': 'application/json' },
      }),
  );
  await assert.rejects(ml.score(request, 'request'), status(504));
  assert.equal(canceled, true);
});
