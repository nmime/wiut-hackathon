import { expect, test } from './auth-fixtures';
import { request as httpRequest } from 'node:http';
import {
  AssessmentListSchema,
  AssessmentSchema,
  AuditListSchema,
  BusinessDetailSchema,
  BusinessListSchema,
  HealthSchema,
  ProblemSchema,
} from '../libs/common/api-contracts/src/index';
import {
  API_URL,
  NO_ML_API_URL,
  AS_OF_DATE,
  fixtureMode,
  importBusiness,
  importInput,
} from './helpers';

test('health and synthetic portfolio comply with the shared API contract', async ({
  request,
}) => {
  const health = await request.get(`${API_URL}/health`);
  expect(health.status()).toBe(200);
  expect(HealthSchema.parse(await health.json())).toEqual({
    status: 'ok',
    database: 'connected',
    ml_configured: true,
    synthetic_data: true,
  });
  const response = await request.get(`${API_URL}/businesses`);
  const portfolio = BusinessListSchema.parse(await response.json());
  expect(response.status()).toBe(200);
  expect(portfolio.synthetic).toBe(true);
  expect(portfolio.items.length).toBeGreaterThanOrEqual(4);
  expect(
    portfolio.items.every((business) => business.data_source === 'synthetic'),
  ).toBeTruthy();
});

test.describe('unconfigured ML', () => {
  test.use({ authApiUrl: NO_ML_API_URL });
  test('the unconfigured ML service persists a failed attempt and never returns a model output', async ({
    request,
  }) => {
    const health = HealthSchema.parse(
      await (await request.get(`${NO_ML_API_URL}/health`)).json(),
    );
    expect(health.ml_configured).toBe(false);
    const business = await importBusiness(
      request,
      'No ML configuration',
      NO_ML_API_URL,
    );
    const response = await request.post(`${NO_ML_API_URL}/assessments`, {
      data: {
        business_id: business.id,
        as_of_date: AS_OF_DATE,
        requested_amount: null,
      },
    });
    expect(response.status()).toBe(503);
    const problem = ProblemSchema.parse(await response.json());
    expect(problem.title).toBe('ML service not configured');
    const history = AssessmentListSchema.parse(
      await (
        await request.get(`${NO_ML_API_URL}/assessments`, {
          params: { business_id: business.id },
        })
      ).json(),
    );
    expect(history.items).toHaveLength(1);
    expect(history.items[0]?.status).toBe('failed');
    expect(history.items[0]?.result).toBeNull();
    expect(history.items[0]?.request_id).toBe(problem.request_id);
    const audit = AuditListSchema.parse(
      await (
        await request.get(`${NO_ML_API_URL}/audit`, {
          params: { business_id: business.id },
        })
      ).json(),
    );
    expect(
      audit.items.filter((event) => event.event_type === 'assessment_failed'),
    ).toHaveLength(1);
    expect(
      audit.items.some((event) => event.event_type === 'assessment_completed'),
    ).toBe(false);
  });
});

test('import rejects malformed and impossible timestamps and real data provenance', async ({
  request,
}) => {
  for (const timestamp of [
    'not-a-timestamp',
    '2025-13-15T10:00:00Z',
    '2025-02-31T10:00:00Z',
  ]) {
    const input = importInput();
    input.transactions[0]!.ts = timestamp;
    const response = await request.post(`${API_URL}/businesses`, {
      data: input,
    });
    expect(response.status(), timestamp).toBe(400);
    const problem = ProblemSchema.parse(await response.json());
    expect(
      problem.errors?.some((error) => error.path.startsWith('transactions')),
    ).toBe(true);
  }
  const response = await request.post(`${API_URL}/businesses`, {
    data: { ...importInput(), data_source: 'bank' },
  });
  expect(response.status()).toBe(400);
});

test('malformed and oversized HTTP bodies return structured problems', async ({
  request,
}) => {
  const malformed = await request.post(`${API_URL}/businesses`, {
    headers: { 'Content-Type': 'application/json' },
    data: '{invalid-json',
  });
  expect(malformed.status()).toBe(400);
  const malformedProblem = ProblemSchema.parse(await malformed.json());
  expect(malformedProblem.request_id).toBe(malformed.headers()['x-request-id']);
  expect(malformed.headers()['content-type']).toContain(
    'application/problem+json',
  );
  // Send an oversized declared body without a multi-megabyte write. Fastify
  // rejects Content-Length early; a full streaming write can race its socket
  // close and produce client-side EPIPE before the response is read.
  const oversized = await new Promise<{
    status: number;
    requestId: string | undefined;
    body: string;
  }>((resolve, reject) => {
    const outgoing = httpRequest(
      `${API_URL}/businesses`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': 3 * 1024 * 1024 + 1,
        },
      },
      (incoming) => {
        let body = '';
        incoming.setEncoding('utf8');
        incoming.on('data', (chunk) => {
          body += chunk;
        });
        incoming.on('end', () =>
          resolve({
            status: incoming.statusCode!,
            requestId: incoming.headers['x-request-id'] as string | undefined,
            body,
          }),
        );
        incoming.on('error', reject);
      },
    );
    outgoing.on('error', reject);
    outgoing.end('{}');
  });
  expect(oversized.status).toBe(413);
  expect(ProblemSchema.parse(JSON.parse(oversized.body)).request_id).toBe(
    oversized.requestId,
  );
});

test('a completed assessment and human decision survive independent API reads', async ({
  request,
}) => {
  const business = await importBusiness(request);
  const detailResponse = await request.get(
    `${API_URL}/businesses/${business.id}`,
  );
  const detail = BusinessDetailSchema.parse(await detailResponse.json());
  expect(detail.transactions).toHaveLength(24);
  expect(detail.monthly_cashflow).toHaveLength(12);
  expect(detail.latest_assessment).toBeNull();

  const scoreResponse = await request.post(`${API_URL}/assessments`, {
    data: {
      business_id: business.id,
      as_of_date: AS_OF_DATE,
      requested_amount: 500,
    },
  });
  expect(scoreResponse.status()).toBe(201);
  const assessment = AssessmentSchema.parse(await scoreResponse.json());
  expect(assessment.status).toBe('completed');
  expect(assessment.result?.business_id).toBe(business.id);
  expect(assessment.result?.as_of_date).toBe(AS_OF_DATE);
  expect(assessment.result?.model_version).toBe('test-only-fixture-v1');
  expect(assessment.input_hash).toMatch(/^[a-f0-9]{64}$/);
  expect(assessment.request_id).toBeTruthy();
  expect(assessment.decision).toBeNull();

  const incomplete = await request.post(
    `${API_URL}/assessments/${assessment.id}/decisions`,
    { data: { decision: 'approved', reviewer_name: 'A', notes: '' } },
  );
  expect(incomplete.status()).toBe(400);
  const decisionResponse = await request.post(
    `${API_URL}/assessments/${assessment.id}/decisions`,
    {
      data: {
        decision: 'needs_information',
        reviewer_name: 'Integration Officer',
        notes: 'Request an updated synthetic operating expense history.',
      },
    },
  );
  expect(decisionResponse.status()).toBe(201);
  const decided = AssessmentSchema.parse(await decisionResponse.json());
  expect(decided.decision?.decision).toBe('needs_information');
  expect(decided.decision?.reviewer_name).toBe('Integration Officer');
  expect(decided.decision?.assessment_id).toBe(assessment.id);

  const duplicate = await request.post(
    `${API_URL}/assessments/${assessment.id}/decisions`,
    {
      data: {
        decision: 'approved',
        reviewer_name: 'Another Officer',
        notes: 'This duplicate must not overwrite the first review.',
      },
    },
  );
  expect(duplicate.status()).toBe(409);
  expect(ProblemSchema.parse(await duplicate.json()).request_id).toBeTruthy();

  const fetched = AssessmentSchema.parse(
    await (await request.get(`${API_URL}/assessments/${assessment.id}`)).json(),
  );
  expect(fetched.decision).toEqual(decided.decision);
  const history = AssessmentListSchema.parse(
    await (
      await request.get(`${API_URL}/assessments`, {
        params: { business_id: business.id },
      })
    ).json(),
  );
  expect(history.items).toHaveLength(1);
  expect(history.items[0]?.id).toBe(assessment.id);
  const refreshedBusiness = BusinessDetailSchema.parse(
    await (await request.get(`${API_URL}/businesses/${business.id}`)).json(),
  );
  expect(refreshedBusiness.latest_assessment?.decision?.id).toBe(
    decided.decision?.id,
  );

  const audit = AuditListSchema.parse(
    await (
      await request.get(`${API_URL}/audit`, {
        params: { business_id: business.id },
      })
    ).json(),
  );
  expect(audit.items.map((event) => event.event_type)).toEqual(
    expect.arrayContaining([
      'business_imported',
      'assessment_requested',
      'assessment_completed',
      'decision_recorded',
      'decision_rejected',
    ]),
  );
  expect(
    audit.items.filter((event) => event.event_type === 'decision_recorded'),
  ).toHaveLength(1);
  expect(
    audit.items.every(
      (event) =>
        event.business_id === business.id && event.request_id.length > 0,
    ),
  ).toBe(true);
  expect(
    audit.items.find((event) => event.event_type === 'decision_recorded')
      ?.actor,
  ).toBe('Integration Officer');
  const serializedAudit = JSON.stringify(audit.items);
  expect(serializedAudit).toContain(assessment.input_hash);
  expect(serializedAudit).toContain('test-only-fixture-v1');
});

test('concurrent human decisions preserve exactly one winner and audit the rejected write', async ({
  request,
}) => {
  const business = await importBusiness(request, 'Concurrent officer review');
  const response = await request.post(`${API_URL}/assessments`, {
    data: {
      business_id: business.id,
      as_of_date: AS_OF_DATE,
      requested_amount: null,
    },
  });
  expect(response.status()).toBe(201);
  const assessment = AssessmentSchema.parse(await response.json());
  const submissions = [
    {
      decision: 'approved',
      reviewer_name: 'Officer One',
      notes: 'First concurrent review with synthetic evidence.',
    },
    {
      decision: 'declined',
      reviewer_name: 'Officer Two',
      notes: 'Second concurrent review with synthetic evidence.',
    },
  ];
  const writes = await Promise.all(
    submissions.map((data) =>
      request.post(`${API_URL}/assessments/${assessment.id}/decisions`, {
        data,
      }),
    ),
  );
  expect(writes.map((write) => write.status()).sort()).toEqual([201, 409]);
  const winner = AssessmentSchema.parse(
    await writes.find((write) => write.status() === 201)!.json(),
  );
  const saved = AssessmentSchema.parse(
    await (await request.get(`${API_URL}/assessments/${assessment.id}`)).json(),
  );
  expect(saved.decision).toEqual(winner.decision);
  const audit = AuditListSchema.parse(
    await (
      await request.get(`${API_URL}/audit`, {
        params: { business_id: business.id },
      })
    ).json(),
  );
  expect(
    audit.items.filter((event) => event.event_type === 'decision_recorded'),
  ).toHaveLength(1);
  expect(
    audit.items.filter((event) => event.event_type === 'decision_rejected'),
  ).toHaveLength(1);
});

test('rejecting future data and missing resources returns correlated problems and audits', async ({
  request,
}) => {
  const business = await importBusiness(request);
  const future = await request.post(`${API_URL}/assessments`, {
    data: {
      business_id: business.id,
      as_of_date: '2025-01-01',
      requested_amount: null,
    },
  });
  expect(future.status()).toBe(400);
  expect(ProblemSchema.parse(await future.json()).request_id).toBeTruthy();
  const audit = AuditListSchema.parse(
    await (
      await request.get(`${API_URL}/audit`, {
        params: { business_id: business.id },
      })
    ).json(),
  );
  expect(
    audit.items.some((event) => event.event_type === 'assessment_rejected'),
  ).toBe(true);
  for (const resource of [
    '/businesses/unknown-business',
    '/assessments/unknown-assessment',
  ]) {
    const response = await request.get(`${API_URL}${resource}`);
    expect(response.status()).toBe(404);
    expect(ProblemSchema.parse(await response.json()).status).toBe(404);
  }
});

for (const [mode, status] of [
  ['malformed', 502],
  ['wrong-business', 502],
  ['unavailable', 503],
  ['timeout', 504],
] as const) {
  test(`${mode} ML responses are rejected and the attempt remains in persisted history`, async ({
    request,
  }) => {
    const business = await importBusiness(request, `Failure ${mode}`);
    await fixtureMode(request, business.id, mode);
    const response = await request.post(`${API_URL}/assessments`, {
      data: {
        business_id: business.id,
        as_of_date: AS_OF_DATE,
        requested_amount: null,
      },
    });
    expect(response.status()).toBe(status);
    const problem = ProblemSchema.parse(await response.json());
    const history = AssessmentListSchema.parse(
      await (
        await request.get(`${API_URL}/assessments`, {
          params: { business_id: business.id },
        })
      ).json(),
    );
    expect(history.items).toHaveLength(1);
    const assessment = history.items[0]!;
    expect(assessment.status).toBe('failed');
    expect(assessment.result).toBeNull();
    expect(assessment.error).toBeTruthy();
    expect(assessment.request_id).toBe(problem.request_id);
    expect(assessment.input_hash).toMatch(/^[a-f0-9]{64}$/);
    const decision = await request.post(
      `${API_URL}/assessments/${assessment.id}/decisions`,
      {
        data: {
          decision: 'approved',
          reviewer_name: 'Integration Officer',
          notes: 'A failed model attempt cannot support this decision.',
        },
      },
    );
    expect(decision.status()).toBe(409);
    const audit = AuditListSchema.parse(
      await (
        await request.get(`${API_URL}/audit`, {
          params: { business_id: business.id },
        })
      ).json(),
    );
    expect(
      audit.items.filter((event) => event.event_type === 'assessment_failed'),
    ).toHaveLength(1);
    expect(
      audit.items.some((event) => event.event_type === 'assessment_completed'),
    ).toBe(false);
    expect(
      audit.items.some((event) => event.event_type === 'decision_rejected'),
    ).toBe(true);
  });
}
