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
  @Get('auth/security') security(@Req() request: FastifyRequest) {
    return this.auth.securityStatus(request.auth!);
  }
  @HttpCode(200) @Post('auth/mfa/setup') setupMfa(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.auth.setupMfa(body, request.auth!, request);
  }
  @HttpCode(200) @Post('auth/mfa/confirm') confirmMfa(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.auth.confirmMfa(body, request.auth!, request);
  }
  @HttpCode(200) @Post('auth/mfa/disable') disableMfa(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.auth.disableMfa(body, request.auth!, request);
  }
  @HttpCode(200) @Post('auth/mfa/recovery-codes') rotateMfaCodes(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.auth.rotateMfaRecoveryCodes(body, request.auth!, request);
  }
  @HttpCode(200) @Post('auth/recovery-key') rotateRecoveryKey(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.auth.rotateAccountRecoveryKey(body, request.auth!, request);
  }
  @HttpCode(200) @Post('auth/password') changePassword(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.auth.changePassword(body, request.auth!, request);
  }
  @Public() @HttpCode(200) @Post('auth/recover') recoverAccount(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
    @Res({ passthrough: true }) reply: FastifyReply,
  ) {
    return this.auth.recoverAccount(body, request, reply);
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
  @Post('auth/showcase-tenants') createShowcaseTenant(
    @Body() body: unknown,
    @Req() request: FastifyRequest,
  ) {
    return this.auth.createTenant(body, request.auth!, request.id, 'showcase');
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
