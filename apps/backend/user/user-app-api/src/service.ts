import { Injectable } from '@nestjs/common';
import { createHash, randomUUID } from 'node:crypto';
import {
  AssessmentListSchema,
  AssessmentSchema,
  AuditListSchema,
  BusinessDetailSchema,
  BusinessImportSchema,
  BusinessListSchema,
  CreateAssessmentSchema,
  DecisionInputSchema,
  HealthSchema,
  ScoreRequestSchema,
  type CreateAssessment,
  type ScoreRequest,
  type DecisionInput,
} from '@wiut/contracts';
import type { AppConfig } from './config.js';
import { Database } from './database.js';
import { MlClient } from './ml.js';
import { ApiProblem, errorMessage, validate } from './problem.js';
import { businessDetail } from './synthetic.js';

function knownBusinessId(body: unknown): string | undefined {
  if (typeof body !== 'object' || body === null || !('business_id' in body))
    return undefined;
  const value = body.business_id;
  return typeof value === 'string' && value.length <= 100 ? value : undefined;
}
export function inputHash(input: unknown) {
  return createHash('sha256')
    .update(JSON.stringify(input) ?? 'null')
    .digest('hex');
}

@Injectable()
export class ProductService {
  constructor(
    private readonly database: Database,
    private readonly ml: MlClient,
    private readonly config: AppConfig,
  ) {}

  async health() {
    await this.database.health();
    return HealthSchema.parse({
      status: 'ok',
      database: 'connected',
      ml_configured: Boolean(this.config.ML_SERVICE_URL),
      synthetic_data: true,
    });
  }

  async businesses() {
    const stored = await this.database.businesses();
    const items = await Promise.all(
      stored.map(async (business) => {
        const {
          transactions: _transactions,
          monthly_cashflow: _monthly,
          ...summary
        } = businessDetail(business);
        return {
          ...summary,
          latest_assessment: await this.database.latestAssessment(business.id),
        };
      }),
    );
    return BusinessListSchema.parse({ items, synthetic: true });
  }
  async business(id: string) {
    const stored = await this.database.business(id);
    if (!stored)
      throw new ApiProblem(
        404,
        'Business not found',
        'The requested synthetic business does not exist.',
      );
    return BusinessDetailSchema.parse({
      ...businessDetail(stored),
      latest_assessment: await this.database.latestAssessment(id),
    });
  }
  async importBusiness(body: unknown, requestId: string) {
    const input = validate(BusinessImportSchema, body);
    const transactions = [...input.transactions].sort((a, b) =>
      a.ts.localeCompare(b.ts),
    );
    const first = new Date(`${transactions[0]!.ts.slice(0, 7)}-01T00:00:00Z`);
    const last = new Date(
      `${transactions.at(-1)!.ts.slice(0, 7)}-01T00:00:00Z`,
    );
    if (
      (last.getUTCFullYear() - first.getUTCFullYear()) * 12 +
        last.getUTCMonth() -
        first.getUTCMonth() >=
      240
    )
      throw new ApiProblem(
        400,
        'Invalid transaction history',
        'Synthetic imports support at most 240 calendar months of transaction history.',
      );
    const business = {
      id: `synthetic-${randomUUID()}`,
      name: input.name,
      sector: input.sector,
      location: input.location,
      archetype: 'Imported synthetic data',
      transactions,
    };
    await this.database.importBusiness(business, requestId);
    return BusinessDetailSchema.parse(businessDetail(business));
  }

  async createAssessment(body: unknown, requestId: string) {
    let input: CreateAssessment;
    let scoringInput: ScoreRequest;
    try {
      input = validate(CreateAssessmentSchema, body);
      const business = await this.database.business(input.business_id);
      if (!business)
        throw new ApiProblem(
          404,
          'Business not found',
          'The requested synthetic business does not exist.',
        );
      const transactions = business.transactions.filter(
        (transaction) => transaction.ts.slice(0, 10) <= input.as_of_date,
      );
      if (transactions.length === 0)
        throw new ApiProblem(
          400,
          'No eligible transactions',
          'Choose an assessment date on or after the first synthetic transaction.',
        );
      scoringInput = validate(ScoreRequestSchema, {
        ...input,
        currency: 'UZS',
        transactions,
      });
    } catch (error) {
      const businessId = knownBusinessId(body);
      if (
        error instanceof ApiProblem &&
        businessId &&
        (await this.database.business(businessId))
      ) {
        await this.database.audit({
          business_id: businessId,
          assessment_id: null,
          event_type: 'assessment_rejected',
          request_id: requestId,
          actor: 'officer',
          metadata: {
            input_hash: inputHash(body),
            reason: error.detail,
            status: error.status,
            ...(error.errors ? { errors: error.errors } : {}),
          },
        });
      }
      throw error;
    }
    const id = randomUUID();
    await this.database.beginAssessment(
      id,
      scoringInput,
      requestId,
      inputHash(scoringInput),
    );
    let result;
    try {
      result = await this.ml.score(scoringInput, requestId);
    } catch (error) {
      await this.database.finishAssessment(
        id,
        null,
        errorMessage(error),
        error instanceof ApiProblem ? error.status : 503,
      );
      throw error;
    }
    await this.database.finishAssessment(id, result, null);
    return AssessmentSchema.parse(await this.database.assessment(id));
  }

  async assessments(businessId?: string) {
    return AssessmentListSchema.parse({
      items: await this.database.assessments(businessId),
    });
  }
  async assessment(id: string) {
    const assessment = await this.database.assessment(id);
    if (!assessment)
      throw new ApiProblem(
        404,
        'Assessment not found',
        'The requested assessment does not exist.',
      );
    return AssessmentSchema.parse(assessment);
  }
  async decide(id: string, body: unknown, requestId: string) {
    const businessId = await this.database.assessmentBusinessId(id);
    if (!businessId)
      throw new ApiProblem(
        404,
        'Assessment not found',
        'The requested assessment does not exist.',
      );
    let input: DecisionInput | undefined;
    try {
      input = validate(DecisionInputSchema, body);
      return AssessmentSchema.parse(
        await this.database.recordDecision(id, input, requestId),
      );
    } catch (error) {
      if (error instanceof ApiProblem) {
        await this.database.audit({
          business_id: businessId,
          assessment_id: id,
          event_type: 'decision_rejected',
          request_id: requestId,
          actor: input?.reviewer_name ?? 'officer',
          metadata: {
            input_hash: inputHash(body),
            reason: error.detail,
            status: error.status,
            ...(input ? { submission: input } : {}),
            ...(error.errors ? { errors: error.errors } : {}),
          },
        });
      }
      throw error;
    }
  }
  async audit(businessId?: string) {
    return AuditListSchema.parse({
      items: await this.database.auditEvents(businessId),
    });
  }
}
