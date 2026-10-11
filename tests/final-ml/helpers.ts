import { randomUUID } from 'node:crypto';
import { expect, type APIRequestContext } from '@playwright/test';
import {
  AssessmentSchema,
  BusinessDetailSchema,
  type BusinessImport,
} from '../../libs/common/api-contracts/src/index';

export const FINAL_API_URL = 'http://127.0.0.1:3012/api';
export const FINAL_ML_URL = 'http://127.0.0.1:8112';
export const FINAL_AS_OF_DATE = '2026-09-30';

// Test-only observations. The future and any expected forecast values are never
// inserted as transactions. These scenarios check behaviour, not real accuracy.
export function finalBusinessInput(
  kind: 'stable' | 'seasonal' | 'declining' | 'elevated',
): BusinessImport {
  const transactions: BusinessImport['transactions'] = [];
  for (let offset = 0; offset < 36; offset++) {
    const date = new Date(Date.UTC(2023, 9 + offset, 1));
    const month = date.getUTCMonth();
    const prefix = `${date.getUTCFullYear()}-${String(month + 1).padStart(2, '0')}`;
    const inflow =
      kind === 'declining'
        ? Math.max(400_000, 12_000_000 * Math.pow(0.94, offset))
        : kind === 'seasonal'
          ? 10_000_000 * (1 + 0.45 * Math.sin((2 * Math.PI * month) / 12))
          : 10_000_000 * (1 + 0.01 * Math.sin(offset));
    const outflow =
      kind === 'declining'
        ? 3_000_000
        : inflow * (kind === 'elevated' ? 0.9999 : 0.3);
    transactions.push(
      {
        ts: `${prefix}-01T10:00:00Z`,
        direction: 'in',
        channel: 'card',
        amount: inflow,
      },
      {
        ts: `${prefix}-01T16:00:00Z`,
        direction: 'out',
        channel: 'transfer',
        amount: outflow,
      },
    );
  }
  return {
    name: `Test-only final ${kind} ${randomUUID().slice(0, 8)}`,
    sector: 'Synthetic final-model integration fixture',
    location: 'Test Tashkent district',
    data_source: 'user_provided',
    amount_unit: 'UZS',
    transactions,
  };
}

export async function importFinalBusiness(
  request: APIRequestContext,
  kind: 'stable' | 'seasonal' | 'declining' | 'elevated',
) {
  const response = await request.post(`${FINAL_API_URL}/businesses`, {
    data: finalBusinessInput(kind),
  });
  expect(response.status(), await response.text()).toBe(201);
  return BusinessDetailSchema.parse(await response.json());
}

export async function assessFinalBusiness(
  request: APIRequestContext,
  businessId: string,
  requestedAmount: number | null = null,
) {
  const response = await request.post(`${FINAL_API_URL}/assessments`, {
    data: {
      business_id: businessId,
      as_of_date: FINAL_AS_OF_DATE,
      requested_amount: requestedAmount,
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  const assessment = AssessmentSchema.parse(await response.json());
  expect(assessment.status).toBe('completed');
  expect(assessment.result?.model_version).toMatch(/^final-v1-/);
  return assessment;
}
