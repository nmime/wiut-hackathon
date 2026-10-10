import { Module } from '@nestjs/common';
import { APP_FILTER, APP_GUARD } from '@nestjs/core';
import type { AppConfig } from './config.js';
import { ProductController } from './controller.js';
import { Database } from './database.js';
import { MlClient } from './ml.js';
import { ProblemFilter } from './problem.js';
import { ProductService } from './service.js';
import { AuthService, AuthGuard } from './auth.js';
import { AuthController } from './auth-controller.js';

export function createAppModule(config: AppConfig) {
  @Module({
    controllers: [ProductController, AuthController],
    providers: [
      { provide: Database, useFactory: () => new Database(config) },
      { provide: MlClient, useFactory: () => new MlClient(config) },
      {
        provide: AuthService,
        inject: [Database],
        useFactory: (database: Database) => new AuthService(database, config),
      },
      { provide: APP_GUARD, useClass: AuthGuard },
      {
        provide: ProductService,
        inject: [Database, MlClient],
        useFactory: (database: Database, ml: MlClient) =>
          new ProductService(database, ml, config),
      },
      { provide: APP_FILTER, useClass: ProblemFilter },
    ],
  })
  class AppModule {}
  return AppModule;
}
