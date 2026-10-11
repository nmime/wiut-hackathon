// Deterministic test fixtures only. Runtime services do not import this module.
import type { Transaction } from '@wiut/contracts';
import type { StoredBusiness } from './business.js';
export { businessDetail, monthlyCashflow } from './business.js';

function random(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

const definitions = [
  {
    id: 'synthetic-bakery',
    name: 'Baraka Bakery',
    sector: 'Food & bakery',
    location: 'Tashkent',
    archetype: 'Stable daily trade',
    base: 900,
    growth: 0.005,
    expense: 0.68,
    volatility: 0.1,
    months: 12,
    seasonal: false,
  },
  {
    id: 'synthetic-textile',
    name: 'Atlas Textile Studio',
    sector: 'Textiles',
    location: 'Samarkand',
    archetype: 'Seasonal demand',
    base: 1700,
    growth: 0.004,
    expense: 0.67,
    volatility: 0.12,
    months: 12,
    seasonal: true,
  },
  {
    id: 'synthetic-grocery',
    name: 'Mahalla Market',
    sector: 'Grocery retail',
    location: 'Bukhara',
    archetype: 'Growing neighborhood shop',
    base: 1300,
    growth: 0.045,
    expense: 0.76,
    volatility: 0.09,
    months: 12,
    seasonal: false,
  },
  {
    id: 'synthetic-cafe',
    name: 'Choy & Coffee',
    sector: 'Cafe',
    location: 'Fergana',
    archetype: 'Declining cash flow',
    base: 1300,
    growth: -0.035,
    expense: 0.82,
    volatility: 0.14,
    months: 12,
    seasonal: false,
  },
  {
    id: 'synthetic-workshop',
    name: 'Usta Repair Workshop',
    sector: 'Repair services',
    location: 'Namangan',
    archetype: 'Irregular contracts',
    base: 1700,
    growth: 0.008,
    expense: 0.62,
    volatility: 0.65,
    months: 12,
    seasonal: false,
  },
  {
    id: 'synthetic-florist',
    name: 'Gul Florist',
    sector: 'Flowers & gifts',
    location: 'Tashkent',
    archetype: 'Short business history',
    base: 600,
    growth: 0.035,
    expense: 0.7,
    volatility: 0.16,
    months: 4,
    seasonal: true,
  },
];

export function generateSyntheticBusinesses(): StoredBusiness[] {
  return definitions.map((definition, index) => {
    const rng = random(7261 + index * 919);
    const transactions: Transaction[] = [];
    for (let offset = 12 - definition.months; offset < 12; offset++) {
      const date = new Date(Date.UTC(2025, 9 + offset, 1));
      const year = date.getUTCFullYear();
      const month = date.getUTCMonth() + 1;
      const seasonalFactor = definition.seasonal
        ? [
            0.76, 0.79, 1.35, 1.08, 1.17, 0.93, 0.73, 0.88, 1.13, 1.1, 1.12,
            1.35,
          ][month - 1]!
        : 1;
      const monthlyInflow =
        definition.base *
        (1 + definition.growth * offset) *
        seasonalFactor *
        (1 + (rng() - 0.5) * definition.volatility);
      for (let dayIndex = 0; dayIndex < 18; dayIndex++) {
        const day = 1 + Math.floor(dayIndex * 1.5);
        const channels = ['card', 'transfer', 'qr', 'cash_in'] as const;
        transactions.push({
          ts: `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}T12:00:00Z`,
          direction: 'in',
          channel: channels[Math.floor(rng() * channels.length)]!,
          amount_index:
            Math.round((monthlyInflow / 18) * (0.8 + rng() * 0.4) * 100) / 100,
        });
      }
      for (let dayIndex = 0; dayIndex < 6; dayIndex++) {
        transactions.push({
          ts: `${year}-${String(month).padStart(2, '0')}-${String(2 + dayIndex * 5).padStart(2, '0')}T17:00:00Z`,
          direction: 'out',
          channel: 'transfer',
          amount_index:
            Math.round(
              ((monthlyInflow * definition.expense) / 6) *
                (0.8 + rng() * 0.4) *
                100,
            ) / 100,
        });
      }
    }
    transactions.sort((a, b) => a.ts.localeCompare(b.ts));
    return {
      id: definition.id,
      name: definition.name,
      sector: definition.sector,
      location: definition.location,
      archetype: definition.archetype,
      data_source: 'synthetic',
      amount_unit: 'index',
      archived_at: null,
      transactions,
    };
  });
}
