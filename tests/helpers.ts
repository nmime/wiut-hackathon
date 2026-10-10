import { randomUUID } from 'node:crypto';
import { expect, type APIRequestContext } from '@playwright/test';
import {
  BusinessDetailSchema,
  type BusinessImport,
} from '../libs/common/api-contracts/src/index';

export const API_URL = 'http://127.0.0.1:3001/api';
export const NO_ML_API_URL = 'http://127.0.0.1:3002/api';
export const FIXTURE_URL = 'http://127.0.0.1:8101';
export const AS_OF_DATE = '2026-09-30';

export function importInput(label = 'API integration'): BusinessImport {
  return {
    name: `${label} ${randomUUID().slice(0, 8)}`,
    sector: 'Synthetic retail',
    location: 'Synthetic Tashkent district',
    data_source: 'synthetic',
    transactions: Array.from({ length: 12 }, (_, index) => [
      {
        ts: `2025-${String(index + 1).padStart(2, '0')}-15T10:00:00Z`,
        direction: 'in' as const,
        channel: 'card' as const,
        amount_index: 100 + index * 5,
      },
      {
        ts: `2025-${String(index + 1).padStart(2, '0')}-20T10:00:00Z`,
        direction: 'out' as const,
        channel: 'transfer' as const,
        amount_index: 60 + index * 2,
      },
    ]).flat(),
  };
}

export async function importBusiness(
  request: APIRequestContext,
  label?: string,
  apiUrl = API_URL,
) {
  const response = await request.post(`${apiUrl}/businesses`, {
    data: importInput(label),
  });
  expect(response.status()).toBe(201);
  return BusinessDetailSchema.parse(await response.json());
}

export async function fixtureMode(
  request: APIRequestContext,
  businessId: string,
  mode: 'success' | 'malformed' | 'wrong-business' | 'unavailable' | 'timeout',
) {
  const response = await request.post(`${FIXTURE_URL}/test/mode`, {
    data: { business_id: businessId, mode },
  });
  expect(response.ok()).toBeTruthy();
}
