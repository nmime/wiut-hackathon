import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  Param,
  Post,
  Req,
  Res,
} from '@nestjs/common';
import type { FastifyReply, FastifyRequest } from 'fastify';
import { AuthService, Public, SessionRefresh } from './auth.js';

@Controller()
export class AuthController {
  constructor(private readonly auth: AuthService) {}
  @Public() @Post('auth/register') register(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ) {
    return this.auth.register(body, request, reply);
  }
  @Public() @HttpCode(200) @Post('auth/login') login(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ) {
    return this.auth.login(body, request, reply);
  }
  @SessionRefresh() @Get('auth/session') session(
    @Req() request: FastifyRequest,
  ) {
    return this.auth.session(request.auth!);
  }
  @HttpCode(200) @Post('auth/logout') logout(
    @Req() request: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ) {
    return this.auth.logout(request.auth!, request.id, reply);
  }
  @Get('team') team(@Req() request: FastifyRequest) {
    return this.auth.team(request.auth!);
  }
  @Post('tenants') createTenant(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.auth.createTenant(body, request.auth!, request.id);
  }
  @HttpCode(200) @Post('tenants/switch') switchTenant(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.auth.switchTenant(body, request.auth!, request.id);
  }
  @Post('invitations') invitation(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.auth.createInvitation(
      body,
      request.auth!,
      request.id,
      request.headers.origin!,
    );
  }
  @HttpCode(200) @Post('invitations/accept') accept(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.auth.acceptInvitation(body, request.auth!, request.id);
  }
  @Delete('invitations/:id') revoke(
    @Param('id') id: string,
    @Req() request: FastifyRequest,
  ) {
    return this.auth.revokeInvitation(id, request.auth!, request.id);
  }
}
