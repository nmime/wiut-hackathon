import { randomUUID } from 'node:crypto';
import { createServer } from 'node:http';

if (process.env.NODE_ENV !== 'test' || process.env.WIUT_TEST_FIXTURE !== '1') {
  throw new Error(
    'The synthetic ML fixture may run only within the explicit test stack.',
  );
}

const modes = new Map();
const validModes = new Set([
  'success',
  'malformed',
  'wrong-business',
  'unavailable',
  'timeout',
]);

function json(response, status, value) {
  response.writeHead(status, { 'Content-Type': 'application/json' });
  response.end(JSON.stringify(value));
}

async function body(request) {
  let value = '';
  for await (const chunk of request) {
    value += chunk;
    if (value.length > 3_000_000) throw new Error('Test request too large');
  }
  return JSON.parse(value);
}

// Deterministic transport fixture only. These values exercise contract handling;
// they make no prediction and must never be used as model output in the product.
function responseFixture(input) {
  const inflow = input.transactions
    .filter((transaction) => transaction.direction === 'in')
    .reduce((sum, transaction) => sum + transaction.amount_index, 0);
  const outflow = input.transactions
    .filter((transaction) => transaction.direction === 'out')
    .reduce((sum, transaction) => sum + transaction.amount_index, 0);
  const months = new Set(
    input.transactions.map((transaction) => transaction.ts.slice(0, 7)),
  ).size;
  const average = inflow / months;
  const surplus = (inflow - outflow) / months;
  return {
    business_id: input.business_id,
    as_of_date: input.as_of_date,
    capacity_score: 72,
    score_band: 'high',
    cashflow_summary: {
      avg_monthly_inflow_index: average,
      inflow_volatility: 0.12,
      net_monthly_surplus_index: surplus,
      trend: 'stable',
    },
    recommended_loan: {
      max_affordable_installment_index: 24,
      suggested_principal_index: 240,
      suggested_term_months: 12,
      rationale:
        'TEST FIXTURE: contract integration assertion, not a lending recommendation.',
    },
    seasonality: {
      monthly_forecast_index: Array.from(
        { length: 12 },
        (_, index) => average + index,
      ),
      weak_months: [1, 2],
      strong_months: [7, 8],
    },
    adaptive_schedule: Array.from({ length: 12 }, (_, index) => ({
      month_offset: index + 1,
      installment_index: index < 2 ? 15 : index < 8 ? 20 : 22.5,
      note: index < 2 ? 'reduced' : index < 8 ? 'normal' : 'increased',
    })),
    explanation: {
      top_factors: [
        {
          factor: 'TEST FIXTURE: observed transaction history',
          impact: 'positive',
          weight: 0.4,
        },
      ],
      advisory: [
        'TEST FIXTURE: validate the transport and record a human review.',
      ],
    },
    confidence: 0.82,
    flags: ['TEST_FIXTURE_ONLY'],
    model_version: 'test-only-fixture-v1',
    request_id: `fixture-${randomUUID()}`,
  };
}

const server = createServer(async (request, response) => {
  try {
    const path = new URL(request.url ?? '/', 'http://127.0.0.1:8101').pathname;
    if (request.method === 'GET' && path === '/health') {
      json(response, 200, { status: 'ok', test_fixture: true });
      return;
    }
    if (request.method === 'POST' && path === '/test/mode') {
      const input = await body(request);
      if (
        typeof input.business_id !== 'string' ||
        !validModes.has(input.mode)
      ) {
        json(response, 400, { error: 'Invalid test fixture mode' });
        return;
      }
      modes.set(input.business_id, input.mode);
      json(response, 200, { configured: true });
      return;
    }
    if (request.method === 'POST' && path === '/score') {
      const input = await body(request);
      const mode = modes.get(input.business_id) ?? 'success';
      if (mode === 'timeout') {
        const timer = setTimeout(
          () => json(response, 200, responseFixture(input)),
          2_000,
        );
        response.on('close', () => clearTimeout(timer));
      } else if (mode === 'unavailable') {
        // Simulate loss of transport, rather than a valid upstream HTTP error.
        request.socket.destroy();
      } else if (mode === 'malformed') {
        json(response, 200, { ...responseFixture(input), capacity_score: 200 });
      } else if (mode === 'wrong-business') {
        json(response, 200, {
          ...responseFixture(input),
          business_id: 'not-the-requested-business',
        });
      } else {
        json(response, 200, responseFixture(input));
      }
      return;
    }
    json(response, 404, { error: 'No such test fixture endpoint' });
  } catch {
    json(response, 400, { error: 'Invalid test fixture request' });
  }
});

server.listen(8101, '127.0.0.1', () =>
  console.log('Test-only ML transport fixture listening on 127.0.0.1:8101'),
);
for (const signal of ['SIGTERM', 'SIGINT'])
  process.on(signal, () => server.close());
