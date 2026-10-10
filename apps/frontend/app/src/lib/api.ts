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
  type BusinessImport,
  type CreateAssessment,
  type DecisionInput,
} from '@wiut/contracts';

type Parser<T> = { parse: (data: unknown) => T };

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public requestId?: string,
  ) {
    super(message);
  }
}

async function request<T>(
  url: string,
  schema: Parser<T>,
  body?: unknown,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${url}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers:
        body === undefined
          ? { Accept: 'application/json' }
          : { Accept: 'application/json', 'Content-Type': 'application/json' },
      credentials: 'omit',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(
      'The API cannot be reached. Check that the backend is running, then retry.',
      0,
    );
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(
      'The API returned an unreadable response. Please retry.',
      response.status,
    );
  }
  if (!response.ok) {
    const problem = ProblemSchema.safeParse(data);
    throw new ApiError(
      problem.success
        ? problem.data.detail
        : `The request failed (${response.status}). Please retry.`,
      response.status,
      problem.success ? problem.data.request_id : undefined,
    );
  }
  try {
    return schema.parse(data);
  } catch {
    throw new ApiError(
      'The API response did not match the expected contract. No unverified data is displayed.',
      response.status,
    );
  }
}

export const api = {
  health: () => request('/health', HealthSchema),
  businesses: () => request('/businesses', BusinessListSchema),
  business: (id: string) =>
    request(`/businesses/${encodeURIComponent(id)}`, BusinessDetailSchema),
  importBusiness: (input: BusinessImport) =>
    request(
      '/businesses',
      BusinessDetailSchema,
      BusinessImportSchema.parse(input),
    ),
  assessments: (businessId?: string) =>
    request(
      `/assessments${businessId ? `?business_id=${encodeURIComponent(businessId)}` : ''}`,
      AssessmentListSchema,
    ),
  assess: (input: CreateAssessment) =>
    request(
      '/assessments',
      AssessmentSchema,
      CreateAssessmentSchema.parse(input),
    ),
  assessment: (id: string) =>
    request(`/assessments/${encodeURIComponent(id)}`, AssessmentSchema),
  decide: (id: string, input: DecisionInput) =>
    request(
      `/assessments/${encodeURIComponent(id)}/decisions`,
      AssessmentSchema,
      DecisionInputSchema.parse(input),
    ),
  audit: (businessId?: string) =>
    request(
      `/audit${businessId ? `?business_id=${encodeURIComponent(businessId)}` : ''}`,
      AuditListSchema,
    ),
};
