import {
  ArgumentsHost,
  Catch,
  ExceptionFilter,
  HttpException,
} from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';
import type { ZodType } from 'zod';

export class ApiProblem extends Error {
  constructor(
    public readonly status: number,
    public readonly title: string,
    public readonly detail: string,
    public readonly errors?: Array<{ path: string; message: string }>,
    public readonly code?: string,
  ) {
    super(detail);
  }
}

export function validate<T>(schema: ZodType<T>, value: unknown): T {
  const result = schema.safeParse(value);
  if (!result.success)
    throw new ApiProblem(
      400,
      'Invalid request',
      'Check the highlighted request fields.',
      result.error.issues.map((issue) => ({
        path: issue.path.join('.'),
        message: issue.message,
      })),
    );
  return result.data;
}

export function errorMessage(error: unknown): string {
  return error instanceof ApiProblem
    ? error.detail
    : 'The service could not complete this request.';
}

@Catch()
export class ProblemFilter implements ExceptionFilter {
  catch(error: unknown, host: ArgumentsHost) {
    const context = host.switchToHttp();
    const reply = context.getResponse<FastifyReply>();
    const request = context.getRequest<FastifyRequest>();
    const parserStatus =
      typeof error === 'object' &&
      error !== null &&
      'code' in error &&
      typeof error.code === 'string' &&
      error.code.startsWith('FST_ERR_') &&
      'statusCode' in error &&
      typeof error.statusCode === 'number' &&
      error.statusCode >= 400 &&
      error.statusCode < 500
        ? error.statusCode
        : undefined;
    const problem =
      error instanceof ApiProblem
        ? error
        : parserStatus
          ? new ApiProblem(
              parserStatus,
              parserStatus === 413 ? 'Request too large' : 'Request rejected',
              parserStatus === 413
                ? 'The JSON request exceeds the 3 MB limit.'
                : 'The server could not parse or accept this request.',
            )
          : error instanceof HttpException
            ? new ApiProblem(
                error.getStatus(),
                error.getStatus() === 404 ? 'Not found' : 'Request rejected',
                error.getStatus() === 404
                  ? 'The requested API resource does not exist.'
                  : 'The server could not accept this request.',
              )
            : new ApiProblem(
                503,
                'Service unavailable',
                'The service could not complete this request. Please retry later.',
              );
    reply
      .status(problem.status)
      .type('application/problem+json')
      .send({
        type: `urn:wiut:problem:${problem.status}`,
        title: problem.title,
        status: problem.status,
        detail: problem.detail,
        request_id: request.id,
        ...(problem.code ? { code: problem.code } : {}),
        ...(problem.errors ? { errors: problem.errors } : {}),
      });
  }
}
