import { randomUUID } from 'node:crypto';
import { expect, type APIRequestContext } from '@playwright/test';
import {
  AssessmentSchema,
  BusinessDetailSchema,
  type BusinessImport,
} from '../../libs/common/api-contracts/src/index';

export const REAL_API_URL = 'http://127.0.0.1:3010/api';
export const REAL_ML_URL = 'http://127.0.0.1:8110';
export const REAL_AS_OF_DATE = '2026-09-30';

// Hand-authored synthetic observations, deliberately outside the training
// generator. No scores, model metrics, or repayments are specified here.
export function realBusinessInput(
  strength: 'positive' | 'negative',
): BusinessImport {
  const transactions: BusinessImport['transactions'] = [];
  for (let month = 0; month < 18; month++) {
    const date = new Date(Date.UTC(2025, 3 + month, 1));
    const prefix = `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`;
    for (let day = 1; day <= 20; day++) {
      const calendarDate = `${prefix}-${String(day).padStart(2, '0')}`;
      transactions.push(
        {
          ts: `${calendarDate}T10:00:00Z`,
          direction: 'in',
          channel: 'card',
          amount_index:
            strength === 'positive'
              ? 10 + month * 0.5
              : Math.max(1, 9 - month * 0.4),
        },
        {
          ts: `${calendarDate}T16:00:00Z`,
          direction: 'out',
          channel: 'transfer',
          amount_index: strength === 'positive' ? 6 : 11,
        },
      );
    }
  }
  return {
    name: `Real ML ${strength} synthetic ${randomUUID().slice(0, 8)}`,
    sector: 'Synthetic model integration retail',
    location: 'Synthetic Tashkent district',
    data_source: 'synthetic',
    transactions,
  };
}

export async function importRealBusiness(
  request: APIRequestContext,
  strength: 'positive' | 'negative',
  amountScale = 1,
) {
  const input = realBusinessInput(strength);
  for (const transaction of input.transactions)
    transaction.amount_index *= amountScale;
  const response = await request.post(`${REAL_API_URL}/businesses`, {
    data: input,
  });
  expect(response.status()).toBe(201);
  return BusinessDetailSchema.parse(await response.json());
}

export async function assessRealBusiness(
  request: APIRequestContext,
  businessId: string,
) {
  const response = await request.post(`${REAL_API_URL}/assessments`, {
    data: {
      business_id: businessId,
      as_of_date: REAL_AS_OF_DATE,
      requested_amount: null,
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  const assessment = AssessmentSchema.parse(await response.json());
  expect(assessment.status).toBe('completed');
  expect(assessment.result).not.toBeNull();
  expect(assessment.result?.model_version).not.toBe('test-only-fixture-v1');
  expect(assessment.result?.flags).not.toContain('TEST_FIXTURE_ONLY');
  return assessment;
}
