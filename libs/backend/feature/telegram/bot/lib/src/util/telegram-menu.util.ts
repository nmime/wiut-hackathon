import type { Locale } from '@app/backend-common-i18n';
import type { TelegramBotContext } from '../type/telegram.type';

export function languageLabel(ctx: TelegramBotContext, locale: Locale): string {
  const selected = ctx.session.locale === locale ? '✓ ' : '';
  const languageKey = `common.language.${locale}` as const;
  return `${selected}${ctx.t(languageKey)}`;
}

export function menuFingerprint(ctx: TelegramBotContext): string {
  return [
    ctx.session.locale,
    ctx.session.currentRoute,
    ctx.session.stack.join('/'),
    ctx.session.auth.linked ? 'linked' : 'public',
  ].join(':');
}
