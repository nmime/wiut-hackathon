import { Body, Controller, Get, Param, Post, Query, Req } from '@nestjs/common';
import type { FastifyRequest } from 'fastify';
import { ApiTags } from '@nestjs/swagger';
import { ApiProblem } from './problem.js';
import { ProductService } from './service.js';
import { Public } from './auth.js';

function filterBusinessId(value: unknown): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== 'string' || value.length === 0 || value.length > 100)
    throw new ApiProblem(
      400,
      'Invalid filter',
      'business_id must be a single nonempty string of at most 100 characters.',
    );
  return value;
}

@ApiTags('Capacity review')
@Controller()
export class ProductController {
  constructor(private readonly product: ProductService) {}
  @Public() @Get('health') health() {
    return this.product.health();
  }
  @Get('businesses') businesses(@Req() request: FastifyRequest) {
    return this.product.businesses(request.auth!);
  }
  @Get('businesses/:id') business(
    @Param('id') id: string,
    @Req() request: FastifyRequest,
  ) {
    return this.product.business(id, request.auth!);
  }
  @Post('businesses') importBusiness(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.product.importBusiness(body, request.id, request.auth!);
  }
  @Post('showcase/generate') generateShowcase(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.product.generateShowcase(body, request.id, request.auth!);
  }
  @Post('assessments') createAssessment(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.product.createAssessment(body, request.id, request.auth!);
  }
  @Get('assessments') assessments(
    @Req() request: FastifyRequest,
    @Query('business_id') businessId?: unknown,
  ) {
    return this.product.assessments(
      request.auth!,
      filterBusinessId(businessId),
    );
  }
  @Get('assessments/:id') assessment(
    @Param('id') id: string,
    @Req() request: FastifyRequest,
  ) {
    return this.product.assessment(id, request.auth!);
  }
  @Post('assessments/:id/decisions') decide(
    @Param('id') id: string,
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.product.decide(id, body, request.id, request.auth!);
  }
  @Get('audit') audit(
    @Req() request: FastifyRequest,
    @Query('business_id') businessId?: unknown,
  ) {
    return this.product.audit(request.auth!, filterBusinessId(businessId));
  }
}
