import 'reflect-metadata';
import { randomUUID } from 'node:crypto';
import type { IncomingMessage } from 'node:http';
import { NestFactory } from '@nestjs/core';
import {
  FastifyAdapter,
  type NestFastifyApplication,
} from '@nestjs/platform-fastify';
import { createAppModule } from './app.js';
import { loadConfig, trustProxyPolicy } from './config.js';
import { setupDocumentation } from './openapi.js';

async function bootstrap() {
  const config = loadConfig();
  const adapter = new FastifyAdapter({
    trustProxy: trustProxyPolicy(config),
    bodyLimit: 3 * 1024 * 1024,
    genReqId: (request: IncomingMessage) => {
      const provided = request.headers['x-request-id'];
      return typeof provided === 'string' &&
        /^[A-Za-z0-9._-]{8,100}$/.test(provided)
        ? provided
        : randomUUID();
    },
    logger: false,
  });
  adapter.getInstance().addHook('onRequest', async (request, reply) => {
    reply.header('x-request-id', request.id);
    reply.header('x-content-type-options', 'nosniff');
    reply.header('referrer-policy', 'no-referrer');
    reply.header('cache-control', 'no-store');
  });
  const app = await NestFactory.create<NestFastifyApplication>(
    createAppModule(config),
    adapter,
    { logger: ['error', 'warn'], abortOnError: false },
  );
  app.setGlobalPrefix('api');
  app.enableCors({
    origin: config.corsOrigins,
    credentials: true,
    methods: ['GET', 'POST', 'DELETE', 'OPTIONS'],
    allowedHeaders: [
      'content-type',
      'x-request-id',
      'x-csrf-token',
      'x-tenant-id',
    ],
    exposedHeaders: ['x-request-id'],
  });
  app.enableShutdownHooks();
  setupDocumentation(app, config);
  await app.listen(config.API_PORT, config.API_HOST);
  console.log(
    `WIUT capacity review API ready at http://${config.API_HOST}:${config.API_PORT}/api; ML ${config.ML_SERVICE_URL ? 'configured' : 'not configured'}.`,
  );
}

bootstrap().catch(() => {
  console.error(
    'The API could not start. Check the environment configuration and PostgreSQL connection.',
  );
  process.exitCode = 1;
});
