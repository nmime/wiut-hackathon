import { randomUUID } from 'node:crypto';
import {
  ShowcaseGenerateSchema,
  type ShowcaseProvenance,
  type Transaction,
} from '@wiut/contracts';
import type { z } from 'zod';
import type { StoredBusiness } from './business.js';
import { ApiProblem } from './problem.js';

// Illustrative scenarios for an explicitly opted-in showcase workspace. This
// generator is not borrower evidence, model training, or an expected-score oracle.
export const SHOWCASE_GENERATOR_VERSION = 'showcase-v1' as const;
export type ShowcaseParameters = Omit<
  z.infer<typeof ShowcaseGenerateSchema>,
  'end_month'
> & {
  end_month: string;
  generator_version: typeof SHOWCASE_GENERATOR_VERSION;
};

const profiles = [
  {
    scenario: 'stable',
    label: 'Stable daily trade',
    sector: 'Retail',
    growth: 0,
    noise: 0.06,
    fixedCost: 0.25,
    variableCost: 0.42,
  },
  {
    scenario: 'seasonal',
    label: 'Seasonal demand',
    sector: 'Seasonal retail',
    growth: 0,
    noise: 0.08,
    fixedCost: 0.3,
    variableCost: 0.38,
  },
  {
    scenario: 'growing',
    label: 'Growing business',
    sector: 'Grocery retail',
    growth: 0.035,
    noise: 0.08,
    fixedCost: 0.25,
    variableCost: 0.48,
  },
  {
    scenario: 'declining',
    label: 'Declining revenue',
    sector: 'Food services',
    growth: -0.035,
    noise: 0.06,
    fixedCost: 0.4,
    variableCost: 0.45,
  },
  {
    scenario: 'volatile',
    label: 'Irregular contracts',
    sector: 'Repair services',
    growth: 0,
    noise: 0.95,
    fixedCost: 0.3,
    variableCost: 0.42,
  },
  {
    scenario: 'short_history',
    label: 'Short business history',
    sector: 'Small retail',
    growth: 0.02,
    noise: 0.12,
    fixedCost: 0.25,
    variableCost: 0.45,
  },
] as const;

function random(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

export function resolveShowcaseParameters(
  input: z.infer<typeof ShowcaseGenerateSchema>,
  now = new Date(),
): ShowcaseParameters {
  const lastCompletedMonth = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 0),
  )
    .toISOString()
    .slice(0, 7);
  const endMonth = input.end_month ?? lastCompletedMonth;
  const end = new Date(`${endMonth}-01T00:00:00Z`);
  const start = new Date(
    Date.UTC(end.getUTCFullYear(), end.getUTCMonth() - input.months + 1, 1),
  );
  if (endMonth > lastCompletedMonth || start.getUTCFullYear() < 2000)
    throw new ApiProblem(
      400,
      'Invalid showcase period',
      'Choose completed calendar months beginning in 2000 or later. Generated transactions cannot be in the current or a future month.',
    );
  return {
    ...input,
    end_month: endMonth,
    generator_version: SHOWCASE_GENERATOR_VERSION,
  };
}

function splitAmount(
  total: number,
  count: number,
  rng: () => number,
): number[] {
  const weights = Array.from({ length: count }, () => 0.5 + rng());
  const weightTotal = weights.reduce((sum, amount) => sum + amount, 0);
  const rounded = Math.round(total);
  const amounts = weights
    .slice(0, -1)
    .map((weight) => Math.max(1, Math.floor((rounded * weight) / weightTotal)));
  amounts.push(rounded - amounts.reduce((sum, amount) => sum + amount, 0));
  return amounts;
}

export function generateShowcaseBusinesses(
  parameters: ShowcaseParameters,
): StoredBusiness[] {
  return Array.from({ length: parameters.count }, (_, batchIndex) => {
    const profile =
      parameters.scenario === 'mixed'
        ? profiles[batchIndex % profiles.length]!
        : profiles.find((item) => item.scenario === parameters.scenario)!;
    const months =
      profile.scenario === 'short_history'
        ? Math.min(parameters.months, 4)
        : parameters.months;
    const provenance: ShowcaseProvenance = {
      generator_version: SHOWCASE_GENERATOR_VERSION,
      seed: parameters.seed,
      scenario: profile.scenario,
      months,
      end_month: parameters.end_month,
      monthly_revenue_uzs: parameters.monthly_revenue_uzs,
      batch_index: batchIndex,
    };
    const rng = random(
      (parameters.seed + Math.imul(batchIndex + 1, 919)) >>> 0,
    );
    const end = new Date(`${parameters.end_month}-01T00:00:00Z`);
    const transactions: Transaction[] = [];
    for (let offset = 0; offset < months; offset++) {
      const date = new Date(
        Date.UTC(
          end.getUTCFullYear(),
          end.getUTCMonth() - months + 1 + offset,
          1,
        ),
      );
      const month = date.toISOString().slice(0, 7);
      const seasonality =
        profile.scenario === 'seasonal'
          ? [
              0.62, 0.7, 1.35, 1.12, 1.08, 0.9, 0.68, 0.76, 1.12, 1.18, 1.3,
              1.42,
            ][date.getUTCMonth()]!
          : 1;
      const revenue =
        parameters.monthly_revenue_uzs *
        Math.pow(1 + profile.growth, offset) *
        seasonality *
        (1 + (rng() - 0.5) * profile.noise);
      const expenses =
        parameters.monthly_revenue_uzs * profile.fixedCost +
        revenue * profile.variableCost;
      const channels = ['card', 'transfer', 'qr', 'cash_in'] as const;
      for (const [index, amount] of splitAmount(revenue, 20, rng).entries()) {
        transactions.push({
          ts: `${month}-${String(1 + Math.floor(index * 1.35)).padStart(2, '0')}T12:00:00Z`,
          direction: 'in',
          channel: channels[Math.floor(rng() * channels.length)]!,
          amount_index: amount,
        });
      }
      for (const [index, amount] of splitAmount(expenses, 8, rng).entries()) {
        transactions.push({
          ts: `${month}-${String(2 + index * 3).padStart(2, '0')}T17:00:00Z`,
          direction: 'out',
          channel: 'transfer',
          amount_index: amount,
        });
      }
    }
    transactions.sort((left, right) => left.ts.localeCompare(right.ts));
    return {
      id: `showcase-${randomUUID()}`,
      name: `[SHOWCASE] ${profile.label} ${batchIndex + 1}`,
      sector: profile.sector,
      location: 'Illustrative scenario',
      archetype: `Generated showcase: ${profile.label}`,
      transactions,
      data_source: 'synthetic',
      amount_unit: 'UZS',
      archived_at: null,
      showcase_provenance: provenance,
    };
  });
}
