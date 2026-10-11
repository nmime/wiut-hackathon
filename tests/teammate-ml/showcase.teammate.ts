import {
  AssessmentListSchema,
  AssessmentSchema,
  AuditListSchema,
  AuthSessionSchema,
  ProblemSchema,
  ShowcaseGenerationSchema,
} from '../../libs/common/api-contracts/src/index';
import { expect, test } from '../auth-fixtures';
import { TEAMMATE_API_URL, TEAMMATE_ML_URL } from './helpers';

test.use({ authApiUrl: TEAMMATE_API_URL });

test('showcase generation works with the unchanged teammate model and records honest short-history refusal', async ({
  request,
  playwright,
}) => {
  const health = await (await request.get(`${TEAMMATE_ML_URL}/health`)).json();
  const created = await request.post(
    `${TEAMMATE_API_URL}/auth/showcase-tenants`,
    {
      data: { name: 'Test-only teammate showcase' },
    },
  );
  expect(created.status(), await created.text()).toBe(201);
  const session = AuthSessionSchema.parse(await created.json());
  const lab = await playwright.request.newContext({
    storageState: await request.storageState(),
    extraHTTPHeaders: {
      origin: 'http://127.0.0.1:5177',
      'x-csrf-token': session.csrf_token,
      'x-tenant-id': session.tenant.id,
    },
  });
  try {
    const generated = await lab.post(`${TEAMMATE_API_URL}/showcase/generate`, {
      data: {
        scenario: 'mixed',
        seed: 20261011,
        months: 24,
        count: 6,
        end_month: '2026-09',
        monthly_revenue_uzs: 30_000_000,
      },
    });
    expect(generated.status()).toBe(201);
    const batch = ShowcaseGenerationSchema.parse(await generated.json());
    for (const business of batch.items) {
      const scored = await lab.post(`${TEAMMATE_API_URL}/assessments`, {
        data: { business_id: business.id, as_of_date: '2026-09-30' },
      });
      if (business.showcase_provenance?.scenario === 'short_history') {
        expect(scored.status()).toBe(502);
        expect(ProblemSchema.parse(await scored.json()).detail).toMatch(
          /six|6 complete/i,
        );
        const history = AssessmentListSchema.parse(
          await (
            await lab.get(`${TEAMMATE_API_URL}/assessments`, {
              params: { business_id: business.id },
            })
          ).json(),
        );
        expect(history.items).toHaveLength(1);
        expect(history.items[0]).toMatchObject({
          status: 'failed',
          result: null,
        });
      } else {
        expect(scored.status(), await scored.text()).toBe(201);
        const assessment = AssessmentSchema.parse(await scored.json());
        expect(assessment.status).toBe('completed');
        expect(assessment.result?.model_version).toBe(health.model_version);
        expect(assessment.result?.loan_terms?.annual_rate).toBe(0.24);
        expect(assessment.result?.flags).toContain('synthetic_training_only');
        const saved = AssessmentSchema.parse(
          await (
            await lab.get(`${TEAMMATE_API_URL}/assessments/${assessment.id}`)
          ).json(),
        );
        expect(saved.result).toEqual(assessment.result);
      }
    }
    const audit = AuditListSchema.parse(
      await (await lab.get(`${TEAMMATE_API_URL}/audit`)).json(),
    );
    expect(
      audit.items.filter(
        (event) => event.event_type === 'showcase_business_generated',
      ),
    ).toHaveLength(6);
    expect(
      audit.items.filter(
        (event) => event.event_type === 'assessment_completed',
      ),
    ).toHaveLength(5);
    expect(
      audit.items.filter((event) => event.event_type === 'assessment_failed'),
    ).toHaveLength(1);
    const after = await (await request.get(`${TEAMMATE_ML_URL}/health`)).json();
    expect(after.model_artifact_sha256).toBe(health.model_artifact_sha256);
    expect(after.bridge_source_sha256).toBe(health.bridge_source_sha256);
  } finally {
    await lab.dispose();
  }
});
