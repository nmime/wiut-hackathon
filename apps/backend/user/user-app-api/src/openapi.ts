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
  AuthRegisterSchema,
  AuthLoginSchema,
  AuthSessionSchema,
  TeamSchema,
  TenantCreateSchema,
  TenantSwitchSchema,
  InvitationCreateSchema,
  InvitationCreateResponseSchema,
  InvitationAcceptSchema,
  SuccessSchema,
} from '@wiut/contracts';
import type { AppConfig } from './config.js';

export function setupDocumentation(app: INestApplication, config: AppConfig) {
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
    AuthRegister: AuthRegisterSchema,
    AuthLogin: AuthLoginSchema,
    AuthSession: AuthSessionSchema,
    Team: TeamSchema,
    TenantCreate: TenantCreateSchema,
    TenantSwitch: TenantSwitchSchema,
    InvitationCreate: InvitationCreateSchema,
    InvitationCreateResponse: InvitationCreateResponseSchema,
    InvitationAccept: InvitationAcceptSchema,
    Success: SuccessSchema,
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
    successStatus: number = input ? 201 : 200,
  ) => ({
    summary,
    tags: ['Synthetic credit review'],
    security: [
      input ? { sessionCookie: [], csrfToken: [] } : { sessionCookie: [] },
    ],
    parameters: [
      ...(parameters ?? []),
      {
        name: 'x-tenant-id',
        in: 'header',
        required: false,
        schema: { type: 'string', format: 'uuid' },
        description:
          'Optional expected active workspace. Mismatch rejects with409 Workspace changed; never chooses the tenant. Ignored on public routes and GET /auth/session.',
      },
    ],
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
      [successStatus]: response(output, 'Success'),
      ...Object.fromEntries(
        [400, 401, 403, 404, 409, 429, 502, 503, 504].map((status) => [
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
        'Synthetic-data demonstration only. Scores express payment capacity; a human records each final decision. Requested amounts are UZS; transactions, cash flow and recommendations remain amount indices without a declared currency conversion. Opaque HttpOnly sessions select a workspace; every domain resource is tenant-scoped. Authenticated mutations require a trusted application Origin and x-csrf-token from /auth/session; login/register also require a trusted Origin. Administrators manage team invitations; admins and officers review synthetic businesses. Decision identities come from the session; reviewer_name input is deprecated and ignored. Lists are bounded to 200 businesses, 100 assessments, 500 domain audit events, 500 members and 100 invitations. Invitations expire after seven days and require the matching email; email ownership is not independently verified. No email delivery, password reset, MFA or external identity provider is included.',
    },
    paths: {
      '/api/health': {
        get: {
          ...operation('Database readiness and ML configuration', 'Health'),
          security: [],
        },
      },
      '/api/auth/register': {
        post: {
          ...operation(
            'Register administrator workspace or accept invitation while registering',
            'AuthSession',
            'AuthRegister',
          ),
          security: [],
        },
      },
      '/api/auth/login': {
        post: {
          ...operation(
            'Sign in with email and password',
            'AuthSession',
            'AuthLogin',
            undefined,
            200,
          ),
          security: [],
        },
      },
      '/api/auth/session': {
        get: operation(
          'Current signed-in user, active tenant, memberships and CSRF token',
          'AuthSession',
        ),
      },
      '/api/auth/logout': {
        post: {
          ...operation('Revoke current session and clear cookie', 'Success'),
          security: [{ sessionCookie: [], csrfToken: [] }],
        },
      },
      '/api/team': {
        get: operation(
          'Administrator-only members and invitations; secret tokens omitted',
          'Team',
        ),
      },
      '/api/tenants': {
        post: operation(
          'Create a workspace and become its administrator; switch active tenant',
          'AuthSession',
          'TenantCreate',
        ),
      },
      '/api/tenants/switch': {
        post: operation(
          'Switch to an existing workspace membership and rotate CSRF token',
          'AuthSession',
          'TenantSwitch',
          undefined,
          200,
        ),
      },
      '/api/invitations': {
        post: operation(
          'Administrator creates a seven-day invitation; token returned once',
          'InvitationCreateResponse',
          'InvitationCreate',
        ),
      },
      '/api/invitations/accept': {
        post: operation(
          'Join invited workspace with matching signed-in email and rotate CSRF token',
          'AuthSession',
          'InvitationAccept',
          undefined,
          200,
        ),
      },
      '/api/invitations/{id}': {
        delete: {
          ...operation(
            'Administrator revokes an invitation in this tenant',
            'Success',
            undefined,
            pathId,
          ),
          security: [{ sessionCookie: [], csrfToken: [] }],
        },
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
    components: {
      schemas: components,
      securitySchemes: {
        sessionCookie: {
          type: 'apiKey',
          in: 'cookie',
          name: config.SESSION_COOKIE_SECURE
            ? '__Host-wiut_session'
            : 'wiut_session',
          description:
            'Opaque session cookie issued by login/register; HttpOnly, SameSite=Strict; Secure enabled by default in production.',
        },
        csrfToken: {
          type: 'apiKey',
          in: 'header',
          name: 'x-csrf-token',
          description:
            'Current session token from GET /api/auth/session; rotates on tenant changes. Also send an allowed application Origin.',
        },
      },
    },
  } as unknown as OpenAPIObject;
  SwaggerModule.setup('api/docs', app, document, {
    jsonDocumentUrl: 'api/openapi.json',
    swaggerOptions: { persistAuthorization: false },
  });
}
