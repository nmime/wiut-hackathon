import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import {
  AssessmentSchema,
  AuthSessionSchema,
  ShowcaseGenerationSchema,
} from '../../libs/common/api-contracts/src/index';
import { expect, test } from '../auth-fixtures';
import { FINAL_API_URL, assessFinalBusiness } from './helpers';

test.use({ authApiUrl: FINAL_API_URL });

type OfferEvidence = {
  principal: number;
  pv_budget: number;
  actual_within_capacity: boolean;
  caps: number[];
  rows: { payment: number }[];
};

type CompletedEvidence = {
  event: string;
  request_id: string;
  result: unknown;
  financial_evidence: {
    assessment: {
      tier: 'p10' | 'p20' | 'p50';
      verdict: string;
      offered: OfferEvidence;
      tiers: Record<'p10' | 'p20' | 'p50', OfferEvidence>;
      comparison: { offered_overload_months: number };
    };
  };
};

// These disclosed generator inputs reproduce the tolerance-sized offer bug.
// They exercise the saved model and solver, without asserting real accuracy.
for (const scenario of [
  {
    name: 'seasonal' as const,
    months: 24,
    seed: 7261,
    rejectsDust: true,
    tier: 'p20',
  },
  {
    name: 'volatile' as const,
    months: 12,
    seed: 4,
    rejectsDust: true,
    tier: 'p20',
  },
  {
    name: 'volatile' as const,
    months: 12,
    seed: 7261,
    rejectsDust: false,
    tier: 'p10',
  },
]) {
  test(`${scenario.name} ${scenario.months}-month showcase seed ${scenario.seed} ${scenario.rejectsDust ? 'rejects an immaterial P10 offer' : 'retains a material P10 offer'} through scoring, persistence and browser`, async ({
    request,
    playwright,
    page,
  }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    const created = await request.post(
      `${FINAL_API_URL}/auth/showcase-tenants`,
      { data: { name: `Test-only ${scenario.name} materiality regression` } },
    );
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
          scenario: scenario.name,
          seed: scenario.seed,
          count: 1,
          months: scenario.months,
          end_month: '2026-09',
          monthly_revenue_uzs: 30_000_000,
        },
      });
      expect(generated.status(), await generated.text()).toBe(201);
      const business = ShowcaseGenerationSchema.parse(await generated.json())
        .items[0]!;
      expect(business.data_source).toBe('synthetic');
      expect(business.showcase_provenance).toMatchObject({
        scenario: scenario.name,
        seed: scenario.seed,
        months: scenario.months,
      });
      const assessment = await assessFinalBusiness(lab, business.id);
      const result = assessment.result!;
      const principal = result.recommended_loan.suggested_principal_index;
      expect(assessment.requested_amount).toBeNull();
      expect(assessment.amount_unit).toBe('UZS');
      expect(result.flags).toContain(
        scenario.rejectsDust ? 'verdict_elevated_risk' : 'verdict_affordable',
      );
      expect(result.flags).not.toContain(
        scenario.rejectsDust ? 'verdict_affordable' : 'verdict_elevated_risk',
      );
      expect(principal).toBeGreaterThan(1_000_000);
      expect(result.loan_terms?.schedule_type).toBe('adaptive');
      expect(result.loan_terms?.annual_rate).toBe(0.24);
      const payments = result.adaptive_schedule.map(
        (row) => row.installment_index,
      );
      expect(payments).toHaveLength(12);
      expect(Math.max(...payments) - Math.min(...payments)).toBeGreaterThan(1);
      const total = payments.reduce((sum, payment) => sum + payment, 0);
      expect(total).toBeCloseTo(result.loan_terms!.total_repayment_index, 2);
      expect(total).toBeCloseTo(
        principal + result.loan_terms!.total_interest_index,
        2,
      );

      const events = (
        await readFile(
          resolve(
            __dirname,
            '../../hybrid-runtime/runtime/final-integration-audit.jsonl',
          ),
          'utf8',
        )
      )
        .trim()
        .split('\n')
        .map((line) => JSON.parse(line) as CompletedEvidence)
        .filter((event) => event.request_id === result.request_id);
      expect(events.map((event) => event.event)).toEqual([
        'assessment_requested',
        'assessment_completed',
      ]);
      const completed = events[1]!;
      expect(completed.result).toEqual(result);
      const financial = completed.financial_evidence.assessment;
      expect(financial.tiers.p10.pv_budget).toBeGreaterThan(0);
      if (scenario.rejectsDust) {
        expect(
          financial.tiers.p10.caps.filter((cap) => cap === 0).length,
        ).toBeGreaterThan(0);
        expect(financial.tiers.p10.principal).toBe(0);
        expect(financial.tiers.p10.rows).toEqual([]);
        expect(financial.tiers.p10.actual_within_capacity).toBe(false);
      } else {
        expect(financial.tiers.p10.principal).toBe(principal);
      }
      expect(financial.tier).toBe(scenario.tier);
      expect(financial.verdict).toBe(
        scenario.rejectsDust ? 'elevatedrisk_officer' : 'affordable',
      );
      for (const offer of Object.values(financial.tiers)) {
        if (offer.principal > 0) {
          expect(offer.principal).toBeGreaterThanOrEqual(
            offer.pv_budget * 0.05,
          );
        }
      }
      expect(financial.offered.principal).toBe(principal);
      expect(financial.offered.actual_within_capacity).toBe(true);
      expect(principal).toBeGreaterThanOrEqual(
        financial.offered.pv_budget * 0.05,
      );
      expect(financial.comparison.offered_overload_months).toBe(0);
      for (const [index, payment] of payments.entries()) {
        expect(payment).toBeLessThanOrEqual(financial.offered.caps[index]! + 1);
      }
      const persisted = AssessmentSchema.parse(
        await (
          await lab.get(`${FINAL_API_URL}/assessments/${assessment.id}`)
        ).json(),
      );
      expect(persisted.result).toEqual(result);
      expect(persisted.input_hash).toMatch(/^[a-f0-9]{64}$/);

      await page.context().addCookies((await lab.storageState()).cookies);
      await page.goto(`/#business/${business.id}?assessment=${assessment.id}`);
      await expect(page.getByTestId('showcase-disclosure')).toBeVisible();
      await expect(
        page.getByText(
          scenario.rejectsDust
            ? 'Elevated risk — officer review required'
            : 'Affordable',
          { exact: true },
        ),
      ).toBeVisible();
      const formattedPrincipal = new Intl.NumberFormat('en-US', {
        maximumFractionDigits: 2,
      }).format(principal);
      const principalBlock = page
        .getByText('Suggested principal', { exact: true })
        .locator('..');
      await expect(
        principalBlock.getByText(formattedPrincipal, { exact: true }),
      ).toBeVisible();
      await expect(
        principalBlock.getByText('UZS', { exact: true }),
      ).toBeVisible();
      await page.reload();
      await expect(
        principalBlock.getByText(formattedPrincipal, { exact: true }),
      ).toBeVisible();
      expect(errors).toEqual([]);
    } finally {
      await lab.dispose();
    }
  });
}
