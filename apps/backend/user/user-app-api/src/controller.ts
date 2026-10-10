import { Body, Controller, Get, Param, Post, Query, Req } from '@nestjs/common';
import type { FastifyRequest } from 'fastify';
import { ApiTags } from '@nestjs/swagger';
import { ApiProblem } from './problem.js';
import { ProductService } from './service.js';

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

@ApiTags('Synthetic credit review')
@Controller()
export class ProductController {
  constructor(private readonly product: ProductService) {}
  @Get('health') health() {
    return this.product.health();
  }
  @Get('businesses') businesses() {
    return this.product.businesses();
  }
  @Get('businesses/:id') business(@Param('id') id: string) {
    return this.product.business(id);
  }
  @Post('businesses') importBusiness(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.product.importBusiness(body, request.id);
  }
  @Post('assessments') createAssessment(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.product.createAssessment(body, request.id);
  }
  @Get('assessments') assessments(@Query('business_id') businessId?: unknown) {
    return this.product.assessments(filterBusinessId(businessId));
  }
  @Get('assessments/:id') assessment(@Param('id') id: string) {
    return this.product.assessment(id);
  }
  @Post('assessments/:id/decisions') decide(
    @Param('id') id: string,
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.product.decide(id, body, request.id);
  }
  @Get('audit') audit(@Query('business_id') businessId?: unknown) {
    return this.product.audit(filterBusinessId(businessId));
  }
}
