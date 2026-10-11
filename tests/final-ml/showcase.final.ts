import {
  AssessmentSchema,
  AuditListSchema,
  AuthSessionSchema,
  BusinessListSchema,
  ShowcaseGenerationSchema,
} from '../../libs/common/api-contracts/src/index';
import { expect, test } from '../auth-fixtures';
import { FINAL_API_URL, FINAL_ML_URL, assessFinalBusiness } from './helpers';

test.use({ authApiUrl: FINAL_API_URL });

test('isolated generated showcase scenarios use the actual final scorer and short histories persist an advisory decline', async ({
  request,
  playwright,
}) => {
  const bank = AuthSessionSchema.parse(
    await (await request.get(`${FINAL_API_URL}/auth/session`)).json(),
  );
  expect(bank.tenant.kind).toBe('bank');
  const health = await (await request.get(`${FINAL_ML_URL}/health`)).json();
  expect(health.serving_mode).toBe('final_combined_model');
  expect(health.model_version).toMatch(/^final-v1-/);
  const created = await request.post(`${FINAL_API_URL}/auth/showcase-tenants`, {
    data: { name: 'Test-only final-model showcase' },
  });
  expect(created.status(), await created.text()).toBe(201);
  const session = AuthSessionSchema.parse(await created.json());
  expect(session.tenant.kind).toBe('showcase');
  const lab = await playwright.request.newContext({
    storageState: await request.storageState(),
    extraHTTPHeaders: {
      origin: 'http://127.0.0.1:5178',
      'x-csrf-token': session.csrf_token,
      'x-tenant-id': session.tenant.id,
    },
  });
  try {
    const generated = await lab.post(`${FINAL_API_URL}/showcase/generate`, {
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
    expect(
      new Set(
        batch.items.map((business) => business.showcase_provenance?.scenario),
      ).size,
    ).toBe(6);
    const threeMonth = await lab.post(`${FINAL_API_URL}/showcase/generate`, {
      data: {
        scenario: 'short_history',
        seed: 20261012,
        count: 1,
        months: 3,
        end_month: '2026-09',
        monthly_revenue_uzs: 30_000_000,
      },
    });
    expect(threeMonth.status(), await threeMonth.text()).toBe(201);
    const shortBatch = ShowcaseGenerationSchema.parse(await threeMonth.json());
    const results = [];
    const shortHistoryLengths: number[] = [];
    for (const business of [...batch.items, ...shortBatch.items]) {
      expect(business.data_source).toBe('synthetic');
      expect(business.amount_unit).toBe('UZS');
      expect(business.showcase_provenance).not.toBeNull();
      const assessment = await assessFinalBusiness(lab, business.id);
      const result = assessment.result!;
      expect(assessment.amount_unit).toBe('UZS');
      expect(result.model_version).toBe(health.model_version);
      expect(result.flags).toContain('final_combined_model');
      expect(result.flags).not.toContain('TEST_FIXTURE_ONLY');
      expect(result.loan_terms?.annual_rate).toBe(0.24);
      expect(
        result.flags.filter((flag) =>
          [
            'verdict_affordable',
            'verdict_elevated_risk',
            'verdict_decline',
          ].includes(flag),
        ),
      ).toHaveLength(1);
      if (business.showcase_provenance?.scenario === 'short_history') {
        shortHistoryLengths.push(business.showcase_provenance.months);
        expect(result.flags).toContain('verdict_decline');
        expect(result.capacity_score).toBe(0);
        expect(result.recommended_loan.suggested_principal_index).toBe(0);
        expect(result.adaptive_schedule).toEqual([]);
      } else if (result.recommended_loan.suggested_principal_index > 0) {
        expect(result.loan_terms!.total_interest_index).toBeGreaterThan(0);
        expect(
          Math.abs(
            result.loan_terms!.total_repayment_index -
              result.recommended_loan.suggested_principal_index -
              result.loan_terms!.total_interest_index,
          ),
        ).toBeLessThanOrEqual(0.01);
      }
      const persisted = AssessmentSchema.parse(
        await (
          await lab.get(`${FINAL_API_URL}/assessments/${assessment.id}`)
        ).json(),
      );
      expect(persisted.result).toEqual(result);
      expect(persisted.input_hash).toMatch(/^[a-f0-9]{64}$/);
      results.push(assessment);
    }
    expect(shortHistoryLengths.sort()).toEqual([3, 4]);
    const first = results[0]!;
    const reviewed = await lab.post(
      `${FINAL_API_URL}/assessments/${first.id}/decisions`,
      {
        data: {
          decision: 'needs_information',
          notes:
            'Showcase-only generated inputs; no real lending or accuracy evidence.',
        },
      },
    );
    expect(reviewed.status(), await reviewed.text()).toBe(201);
    expect(
      AssessmentSchema.parse(await reviewed.json()).decision,
    ).not.toBeNull();
    const audit = AuditListSchema.parse(
      await (await lab.get(`${FINAL_API_URL}/audit`)).json(),
    );
    expect(
      audit.items.filter(
        (row) => row.event_type === 'showcase_business_generated',
      ),
    ).toHaveLength(7);
    expect(
      audit.items.filter((row) => row.event_type === 'assessment_completed'),
    ).toHaveLength(7);
    expect(
      audit.items.filter((row) => row.event_type === 'assessment_failed'),
    ).toHaveLength(0);
    expect(JSON.stringify(audit.items)).toContain(health.model_version);
    const switched = await lab.post(`${FINAL_API_URL}/tenants/switch`, {
      data: { tenant_id: bank.tenant.id },
    });
    expect(switched.status()).toBe(200);
    expect(AuthSessionSchema.parse(await switched.json()).tenant.kind).toBe(
      'bank',
    );
    expect(
      BusinessListSchema.parse(
        await (await request.get(`${FINAL_API_URL}/businesses`)).json(),
      ).items,
    ).toEqual([]);
    expect(
      (await request.get(`${FINAL_API_URL}/assessments/${first.id}`)).status(),
    ).toBe(404);
    const after = await (await request.get(`${FINAL_ML_URL}/health`)).json();
    expect(after.model_artifact_sha256).toBe(health.model_artifact_sha256);
  } finally {
    await lab.dispose();
  }
});
