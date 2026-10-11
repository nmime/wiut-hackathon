import {
  AssessmentSchema,
  AuditListSchema,
  AuthSessionSchema,
  BusinessListSchema,
  ShowcaseGenerationSchema,
} from '../../libs/common/api-contracts/src/index';
import { expect, test } from '../auth-fixtures';
import { REAL_API_URL, REAL_AS_OF_DATE, REAL_ML_URL } from './helpers';

test.use({ authApiUrl: REAL_API_URL });

test('generated showcase histories run through the actual frozen scorer, persisted review, and isolated bank switch', async ({
  request,
  playwright,
}) => {
  const bank = AuthSessionSchema.parse(
    await (await request.get(`${REAL_API_URL}/auth/session`)).json(),
  );
  const modelHealth = await (await request.get(`${REAL_ML_URL}/health`)).json();
  const created = await request.post(`${REAL_API_URL}/auth/showcase-tenants`, {
    data: { name: 'Test-only real-model showcase' },
  });
  expect(created.status(), await created.text()).toBe(201);
  const session = AuthSessionSchema.parse(await created.json());
  const lab = await playwright.request.newContext({
    storageState: await request.storageState(),
    extraHTTPHeaders: {
      origin: 'http://127.0.0.1:5176',
      'x-csrf-token': session.csrf_token,
      'x-tenant-id': session.tenant.id,
    },
  });
  try {
    const generated = await lab.post(`${REAL_API_URL}/showcase/generate`, {
      data: {
        scenario: 'mixed',
        seed: 20261011,
        count: 6,
        months: 24,
        end_month: '2026-09',
        monthly_revenue_uzs: 30_000_000,
      },
    });
    expect(generated.status(), await generated.text()).toBe(201);
    const batch = ShowcaseGenerationSchema.parse(await generated.json());
    const results = [];
    for (const business of batch.items) {
      const scored = await lab.post(`${REAL_API_URL}/assessments`, {
        data: { business_id: business.id, as_of_date: REAL_AS_OF_DATE },
      });
      expect(scored.status(), await scored.text()).toBe(201);
      const assessment = AssessmentSchema.parse(await scored.json());
      expect(assessment.status).toBe('completed');
      expect(assessment.amount_unit).toBe('UZS');
      expect(assessment.result?.model_version).toBe(modelHealth.model_version);
      expect(assessment.result?.flags).not.toContain('TEST_FIXTURE_ONLY');
      expect(assessment.result?.model_version).not.toBe('test-only-fixture-v1');
      const persisted = AssessmentSchema.parse(
        await (
          await lab.get(`${REAL_API_URL}/assessments/${assessment.id}`)
        ).json(),
      );
      expect(persisted.result).toEqual(assessment.result);
      expect(persisted.input_hash).toMatch(/^[a-f0-9]{64}$/);
      results.push(assessment);
    }
    const first = results[0]!;
    const reviewed = await lab.post(
      `${REAL_API_URL}/assessments/${first.id}/decisions`,
      {
        data: {
          decision: 'needs_information',
          notes:
            'Showcase-only human review of generated inputs, not actual lending evidence.',
        },
      },
    );
    expect(reviewed.status()).toBe(201);
    expect(
      AssessmentSchema.parse(await reviewed.json()).decision,
    ).not.toBeNull();
    const audit = AuditListSchema.parse(
      await (await lab.get(`${REAL_API_URL}/audit`)).json(),
    );
    expect(
      audit.items.filter((row) => row.event_type === 'assessment_completed'),
    ).toHaveLength(6);
    expect(
      audit.items.filter(
        (row) => row.event_type === 'showcase_business_generated',
      ),
    ).toHaveLength(6);
    expect(JSON.stringify(audit.items)).toContain(modelHealth.model_version);
    const switched = await lab.post(`${REAL_API_URL}/tenants/switch`, {
      data: { tenant_id: bank.tenant.id },
    });
    expect(switched.status()).toBe(200);
    expect(
      BusinessListSchema.parse(
        await (await request.get(`${REAL_API_URL}/businesses`)).json(),
      ).items,
    ).toEqual([]);
    expect(
      (await request.get(`${REAL_API_URL}/assessments/${first.id}`)).status(),
    ).toBe(404);
    const after = await (await request.get(`${REAL_ML_URL}/health`)).json();
    expect(after.model_artifact_sha256).toBe(modelHealth.model_artifact_sha256);
  } finally {
    await lab.dispose();
  }
});
