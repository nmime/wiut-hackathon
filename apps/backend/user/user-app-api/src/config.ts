import { existsSync } from 'node:fs';
import { dirname, join, parse } from 'node:path';
import { fileURLToPath } from 'node:url';
import { config as dotenv } from 'dotenv';
import { z } from 'zod';

function findEnvironmentFile(): string | undefined {
  let directory = dirname(fileURLToPath(import.meta.url));
  while (directory !== parse(directory).root) {
    if (existsSync(join(directory, 'pnpm-workspace.yaml')))
      return join(directory, '.env');
    directory = dirname(directory);
  }
  return undefined;
}

const url = (protocols: string[]) =>
  z
    .string()
    .url()
    .refine(
      (value) => protocols.includes(new URL(value).protocol),
      'Unsupported URL protocol',
    );
const ConfigSchema = z.object({
  NODE_ENV: z
    .enum(['development', 'test', 'production'])
    .default('development'),
  DATABASE_URL: url(['postgres:', 'postgresql:']).default(
    'postgresql://wiut:wiut_dev@localhost:55432/wiut',
  ),
  API_HOST: z.string().min(1).default('127.0.0.1'),
  API_PORT: z.coerce.number().int().min(1).max(65535).default(3000),
  ML_SERVICE_URL: url(['http:', 'https:'])
    .refine((value) => {
      const parsed = new URL(value);
      return (
        !parsed.username && !parsed.password && !parsed.hash && !parsed.search
      );
    }, 'ML URL must not contain credentials, query parameters, or fragments')
    .optional(),
  ML_TIMEOUT_MS: z.coerce.number().int().min(100).max(60000).default(8000),
  CORS_ORIGINS: z
    .string()
    .default('http://localhost:5173,http://127.0.0.1:5173'),
});

export type AppConfig = ReturnType<typeof loadConfig>;

export function loadConfig(environment: NodeJS.ProcessEnv = process.env) {
  if (environment === process.env) {
    const path = findEnvironmentFile();
    if (path) dotenv({ path, quiet: true });
  }
  const values = {
    ...environment,
    ML_SERVICE_URL: environment.ML_SERVICE_URL?.trim() || undefined,
  };
  const result = ConfigSchema.safeParse(values);
  if (!result.success)
    throw new Error(
      `Invalid environment: ${result.error.issues.map((issue) => issue.path.join('.')).join(', ')}`,
    );
  const origins = result.data.CORS_ORIGINS.split(',')
    .map((origin) => origin.trim())
    .filter(Boolean);
  if (
    origins.length === 0 ||
    origins.some((origin) => {
      try {
        const parsed = new URL(origin);
        return (
          !['http:', 'https:'].includes(parsed.protocol) ||
          parsed.origin !== origin
        );
      } catch {
        return true;
      }
    })
  )
    throw new Error(
      'Invalid environment: CORS_ORIGINS must be a comma-separated list of HTTP origins',
    );
  return { ...result.data, corsOrigins: origins };
}
