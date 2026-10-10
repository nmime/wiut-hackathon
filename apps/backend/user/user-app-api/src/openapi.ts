import { SwaggerModule, type OpenAPIObject } from '@nestjs/swagger';
import type { INestApplication } from '@nestjs/common';
import { z } from 'zod';
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
  ProblemSchema,
} from '@wiut/contracts';

export function setupDocumentation(app: INestApplication) {
  const schemas = {
    Health: HealthSchema,
    Businesses: BusinessListSchema,
    Business: BusinessDetailSchema,
    BusinessImport: BusinessImportSchema,
    AssessmentInput: CreateAssessmentSchema,
    Assessment: AssessmentSchema,
    Assessments: AssessmentListSchema,
    DecisionInput: DecisionInputSchema,
    Audit: AuditListSchema,
    Problem: ProblemSchema,
  };
  const components = Object.fromEntries(
    Object.entries(schemas).map(([name, schema]) => {
      const json = z.toJSONSchema(schema, { unrepresentable: 'any' });
      const { $schema: _dialect, ...body } = json;
      return [name, body];
    }),
  );
  const response = (schema: string, description: string) => ({
    description,
    content: {
      'application/json': {
        schema: { $ref: `#/components/schemas/${schema}` },
      },
    },
  });
  const operation = (
    summary: string,
    output: string,
    input?: string,
    parameters?: Array<Record<string, unknown>>,
  ) => ({
    summary,
    tags: ['Synthetic credit review'],
    ...(parameters ? { parameters } : {}),
    ...(input
      ? {
          requestBody: {
            required: true,
            content: {
              'application/json': {
                schema: { $ref: `#/components/schemas/${input}` },
              },
            },
          },
        }
      : {}),
    responses: {
      [input ? '201' : '200']: response(output, 'Success'),
      ...Object.fromEntries(
        [400, 404, 409, 502, 503, 504].map((status) => [
          status,
          {
            description:
              'Request rejected or service unavailable. Assessment and human decision rejections for known businesses are audited.',
            content: {
              'application/problem+json': {
                schema: { $ref: '#/components/schemas/Problem' },
              },
            },
          },
        ]),
      ),
    },
  });
  const pathId = [
    { name: 'id', in: 'path', required: true, schema: { type: 'string' } },
  ];
  const businessFilter = [
    {
      name: 'business_id',
      in: 'query',
      required: false,
      schema: { type: 'string', maxLength: 100 },
    },
  ];
  const document = {
    openapi: '3.1.0',
    info: {
      title: 'WIUT capacity review API',
      version: '0.1.0',
      description:
        'Synthetic-data demonstration only. Scores express payment capacity; a human records each final decision. Requested loan amounts are UZS as required by the ML input contract. Transactions, cash flow, and model recommendations are amount indices with no declared currency conversion. No authentication is provided; use only in a trusted local demonstration. Lists are bounded to 200 businesses, 100 assessments, and 500 audit events.',
    },
    paths: {
      '/api/health': {
        get: operation('Database readiness and ML configuration', 'Health'),
      },
      '/api/businesses': {
        get: operation('List synthetic businesses', 'Businesses'),
        post: operation(
          'Import explicitly synthetic transactions (maximum 240 months)',
          'Business',
          'BusinessImport',
        ),
      },
      '/api/businesses/{id}': {
        get: operation(
          'Business transactions and observed cash flow',
          'Business',
          undefined,
          pathId,
        ),
      },
      '/api/assessments': {
        get: operation(
          'Recent completed and failed assessments',
          'Assessments',
          undefined,
          businessFilter,
        ),
        post: operation(
          'Persist an attempt and call the configured ML /score endpoint',
          'Assessment',
          'AssessmentInput',
        ),
      },
      '/api/assessments/{id}': {
        get: operation(
          'Read an assessment with its human decision',
          'Assessment',
          undefined,
          pathId,
        ),
      },
      '/api/assessments/{id}/decisions': {
        post: operation(
          'Record the first human decision atomically',
          'Assessment',
          'DecisionInput',
          pathId,
        ),
      },
      '/api/audit': {
        get: operation(
          'Read durable assessment and decision audit events',
          'Audit',
          undefined,
          businessFilter,
        ),
      },
    },
    components: { schemas: components },
  } as unknown as OpenAPIObject;
  SwaggerModule.setup('api/docs', app, document, {
    jsonDocumentUrl: 'api/openapi.json',
    swaggerOptions: { persistAuthorization: false },
  });
}
