import { randomUUID } from 'node:crypto';
import { expect, type APIRequestContext } from '@playwright/test';
import {
  AssessmentSchema,
  BusinessDetailSchema,
  type BusinessImport,
} from '../../libs/common/api-contracts/src/index';

export const TEAMMATE_API_URL = 'http://127.0.0.1:3011/api';
export const TEAMMATE_ML_URL = 'http://127.0.0.1:8111';
export const TEAMMATE_AS_OF = '2025-09-30';

// Explicitly fabricated test observations. No model score, forecast, repayment
// or future outcome is specified here, and these are never production examples.
export function teammateBusinessInput(
  strength: 'positive' | 'negative',
): BusinessImport {
  const transactions: BusinessImport['transactions'] = [];
  for (let month = 0; month < 24; month++) {
    const date = new Date(Date.UTC(2023, 9 + month, 1));
    const prefix = `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`;
    for (let day = 1; day <= 20; day++) {
      const calendarDate = `${prefix}-${String(day).padStart(2, '0')}`;
      const seasonal = Math.sin((month * Math.PI) / 6);
      transactions.push(
        {
          ts: `${calendarDate}T10:00:00Z`,
          direction: 'in',
          channel: 'card',
          amount:
            (strength === 'positive'
              ? 24 + 3 * seasonal + month * 0.2
              : 3 + seasonal) * 100_000,
        },
        {
          ts: `${calendarDate}T16:00:00Z`,
          direction: 'out',
          channel: 'transfer',
          amount: (strength === 'positive' ? 7 : 15) * 100_000,
        },
      );
    }
  }
  return {
    name: `Test-only teammate ${strength} ${randomUUID().slice(0, 8)}`,
    sector: 'Test candidate integration',
    location: 'Test Tashkent district',
    data_source: 'user_provided',
    amount_unit: 'UZS',
    transactions,
  };
}

export async function importTeammateBusiness(
  request: APIRequestContext,
  strength: 'positive' | 'negative',
) {
  const response = await request.post(`${TEAMMATE_API_URL}/businesses`, {
    data: teammateBusinessInput(strength),
  });
  expect(response.status(), await response.text()).toBe(201);
  return BusinessDetailSchema.parse(await response.json());
}

export async function assessTeammateBusiness(
  request: APIRequestContext,
  businessId: string,
  requestedAmount: number | null = null,
) {
  const response = await request.post(`${TEAMMATE_API_URL}/assessments`, {
    data: {
      business_id: businessId,
      as_of_date: TEAMMATE_AS_OF,
      requested_amount: requestedAmount,
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  const assessment = AssessmentSchema.parse(await response.json());
  expect(assessment.status).toBe('completed');
  expect(assessment.amount_unit).toBe('UZS');
  expect(assessment.result).not.toBeNull();
  return assessment;
}
