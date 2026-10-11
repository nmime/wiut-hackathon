import {
  ScoreResponseSchema,
  type ScoreRequest,
  type ScoreResponse,
} from '@wiut/contracts';
import { z } from 'zod';
import type { AppConfig } from './config.js';
import { ApiProblem } from './problem.js';

export const MAX_ML_RESPONSE_BYTES = 2 * 1024 * 1024;
export const MAX_ML_ERROR_BYTES = 16 * 1024;

const rejectionReasons = {
  insufficient_history:
    'The teammate candidate needs at least 6 complete months of transaction history. Import more history or use the real-data blend.',
  month_end_required:
    'The teammate candidate requires a completed calendar month-end assessment date. Select the latest completed month-end or use the real-data blend.',
  unsupported_calendar:
    'The candidate model does not support this assessment calendar. Choose a supported date.',
  invalid_input:
    'Candidate input could not be validated. Check transaction dates, amounts and supported UZS currency.',
} as const;
const rejectionSchema = z
  .object({
    code: z.enum([
      'insufficient_history',
      'month_end_required',
      'unsupported_calendar',
      'invalid_input',
    ]),
    detail: z
      .string()
      .trim()
      .min(1)
      .max(500)
      .regex(/^[\p{L}\p{N} ,.!?()'_%+-]+$/u)
      .refine(
        (value) =>
          !/\b(?:traceback|exception|stack(?:trace)?|password|secret|token|authorization|bearer|private|api[ _-]?key|sqlstate|credentials?|typeerror|valueerror|runtimeerror|postgres(?:ql)?)\b/i.test(
            value,
          ),
      ),
  })
  .strict();

async function rejectionReason(
  response: Response,
  signal: AbortSignal,
): Promise<string | undefined> {
  if (
    !/^application\/(?:[a-z0-9_.+-]+\+)?json$/i.test(
      response.headers.get('content-type')?.split(';')[0]?.trim() ?? '',
    ) ||
    Number(response.headers.get('content-length')) > MAX_ML_ERROR_BYTES ||
    !response.body
  ) {
    void response.body?.cancel().catch(() => undefined);
    return;
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  let onAbort = () => {};
  const aborted = new Promise<never>((_resolve, reject) => {
    onAbort = () => {
      void reader.cancel().catch(() => undefined);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    signal.addEventListener('abort', onAbort, { once: true });
  });
  try {
    if (signal.aborted) {
      void reader.cancel().catch(() => undefined);
      throw new DOMException('Aborted', 'AbortError');
    }
    while (true) {
      const { done, value } = await Promise.race([reader.read(), aborted]);
      if (done) break;
      size += value.byteLength;
      if (size > MAX_ML_ERROR_BYTES) {
        void reader.cancel().catch(() => undefined);
        return;
      }
      chunks.push(value);
    }
    const parsed = rejectionSchema.safeParse(
      JSON.parse(Buffer.concat(chunks).toString('utf8')),
    );
    // Only local text is exposed; even an approved code cannot relay arbitrary
    // upstream diagnostics, paths, secrets or exception messages to a borrower.
    return parsed.success ? rejectionReasons[parsed.data.code] : undefined;
  } catch (error) {
    if (signal.aborted) throw error;
    void reader.cancel().catch(() => undefined);
    return;
  } finally {
    signal.removeEventListener('abort', onAbort);
    reader.releaseLock();
  }
}

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
        const reason = await rejectionReason(response, controller.signal);
        throw new ApiProblem(
          502,
          'ML service rejected the request',
          `The ML service returned HTTP ${response.status}.${reason ? ` ${reason}` : ''} This attempt has been saved.`,
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
