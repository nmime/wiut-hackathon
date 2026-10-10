import { Module } from '@nestjs/common';
import { APP_FILTER } from '@nestjs/core';
import type { AppConfig } from './config.js';
import { ProductController } from './controller.js';
import { Database } from './database.js';
import { MlClient } from './ml.js';
import { ProblemFilter } from './problem.js';
import { ProductService } from './service.js';

export function createAppModule(config: AppConfig) {
  @Module({
    controllers: [ProductController],
    providers: [
      { provide: Database, useFactory: () => new Database(config) },
      { provide: MlClient, useFactory: () => new MlClient(config) },
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
