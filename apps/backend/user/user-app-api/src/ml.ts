import {
  ScoreResponseSchema,
  type ScoreRequest,
  type ScoreResponse,
} from '@wiut/contracts';
import type { AppConfig } from './config.js';
import { ApiProblem } from './problem.js';

export const MAX_ML_RESPONSE_BYTES = 2 * 1024 * 1024;

export class MlClient {
  constructor(
    private readonly config: Pick<
      AppConfig,
      'ML_SERVICE_URL' | 'ML_TIMEOUT_MS'
    >,
    private readonly fetcher: typeof fetch = fetch,
  ) {}

  async score(
    request: ScoreRequest,
    requestId: string,
  ): Promise<ScoreResponse> {
    if (!this.config.ML_SERVICE_URL)
      throw new ApiProblem(
        503,
        'ML service not configured',
        'Connect the teammate’s ML service to generate a capacity assessment. This attempt has been saved.',
      );
    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(),
      this.config.ML_TIMEOUT_MS,
    );
    try {
      const response = await this.fetcher(
        `${this.config.ML_SERVICE_URL.replace(/\/$/, '')}/score`,
        {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            accept: 'application/json',
            'x-request-id': requestId,
          },
          body: JSON.stringify(request),
          signal: controller.signal,
          redirect: 'error',
        },
      );
      if (!response.ok) {
        await response.body?.cancel();
        throw new ApiProblem(
          502,
          'ML service rejected the request',
          `The ML service returned HTTP ${response.status}. This attempt has been saved.`,
        );
      }
      if (
        !response.headers
          .get('content-type')
          ?.toLowerCase()
          .includes('application/json')
      ) {
        await response.body?.cancel();
        throw new ApiProblem(
          502,
          'Invalid ML response',
          'The ML service must return a JSON scoring response. This attempt has been saved.',
        );
      }
      const declaredLength = Number(response.headers.get('content-length'));
      if (declaredLength > MAX_ML_RESPONSE_BYTES) {
        await response.body?.cancel();
        throw new ApiProblem(
          502,
          'Invalid ML response',
          'The ML response exceeded the allowed size. This attempt has been saved.',
        );
      }
      if (!response.body)
        throw new ApiProblem(
          502,
          'Invalid ML response',
          'The ML service returned an empty response. This attempt has been saved.',
        );
      const reader = response.body.getReader();
      const chunks: Uint8Array[] = [];
      let size = 0;
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > MAX_ML_RESPONSE_BYTES) {
            await reader.cancel();
            throw new ApiProblem(
              502,
              'Invalid ML response',
              'The ML response exceeded the allowed size. This attempt has been saved.',
            );
          }
          chunks.push(value);
        }
      } finally {
        reader.releaseLock();
      }
      let body: unknown;
      try {
        body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      } catch {
        throw new ApiProblem(
          502,
          'Invalid ML response',
          'The ML service returned malformed JSON. This attempt has been saved.',
        );
      }
      const parsed = ScoreResponseSchema.safeParse(body);
      if (
        !parsed.success ||
        parsed.data.business_id !== request.business_id ||
        parsed.data.as_of_date !== request.as_of_date
      )
        throw new ApiProblem(
          502,
          'Invalid ML response',
          'The ML response did not match the scoring contract or requested business and date. This attempt has been saved.',
        );
      return parsed.data;
    } catch (error) {
      if (error instanceof ApiProblem) throw error;
      if (controller.signal.aborted)
        throw new ApiProblem(
          504,
          'ML request timed out',
          'The ML service did not respond in time. This attempt has been saved; retry when the service is ready.',
        );
      throw new ApiProblem(
        503,
        'ML service unavailable',
        'The ML service could not be reached. This attempt has been saved; retry when the service is ready.',
      );
    } finally {
      clearTimeout(timer);
    }
  }
}
