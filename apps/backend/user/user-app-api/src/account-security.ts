import {
  createCipheriv,
  createDecipheriv,
  createHash,
  createHmac,
  randomBytes,
  timingSafeEqual,
} from 'node:crypto';
import { ApiProblem } from './problem.js';

const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
export function encodeBase32(bytes: Buffer): string {
  let bits = 0,
    value = 0,
    result = '';
  for (const byte of bytes) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      bits -= 5;
      result += alphabet[(value >>> bits) & 31];
    }
    value &= (1 << bits) - 1;
  }
  if (bits) result += alphabet[(value << (5 - bits)) & 31];
  return result;
}
export function decodeBase32(secret: string): Buffer {
  if (!/^[A-Z2-7]+$/.test(secret)) throw new Error('Invalid base32 secret');
  let bits = 0,
    value = 0;
  const bytes: number[] = [];
  for (const character of secret) {
    value = (value << 5) | alphabet.indexOf(character);
    bits += 5;
    if (bits >= 8) {
      bits -= 8;
      bytes.push((value >>> bits) & 255);
    }
    value &= (1 << bits) - 1;
  }
  if (value !== 0 || encodeBase32(Buffer.from(bytes)) !== secret)
    throw new Error('Noncanonical base32 secret');
  return Buffer.from(bytes);
}
export const newTotpSecret = () => encodeBase32(randomBytes(20));
export function hotp(
  secret: string,
  counter: number,
  digits: 6 | 8 = 6,
): string {
  if (!Number.isSafeInteger(counter) || counter < 0)
    throw new Error('Invalid OTP counter');
  const buffer = Buffer.alloc(8);
  buffer.writeBigUInt64BE(BigInt(counter));
  const digest = createHmac('sha1', decodeBase32(secret))
    .update(buffer)
    .digest();
  const offset = digest[digest.length - 1]! & 15;
  return ((digest.readUInt32BE(offset) & 0x7fffffff) % 10 ** digits)
    .toString()
    .padStart(digits, '0');
}
export function totpCounter(
  secret: string,
  code: string,
  lastCounter: number | null,
  now = Date.now(),
): number | null {
  if (!/^\d{6}$/.test(code)) return null;
  const current = Math.floor(now / 30000);
  // A consumed step cannot be reused, even when an adjacent clock step matches.
  let matched: number | null = null;
  for (const counter of [current, current - 1, current + 1]) {
    if (counter < 0 || (lastCounter !== null && counter <= lastCounter))
      continue;
    if (
      timingSafeEqual(Buffer.from(hotp(secret, counter)), Buffer.from(code)) &&
      matched === null
    )
      matched = counter;
  }
  return matched;
}
function encryptionKey(key: string | undefined): Buffer {
  if (!key || !/^[a-f0-9]{64}$/i.test(key))
    throw new ApiProblem(
      503,
      'Authenticator unavailable',
      'Authenticator verification is unavailable. Use an unused recovery code or your account recovery key.',
    );
  return Buffer.from(key, 'hex');
}
export function encryptTotp(
  secret: string,
  key: string | undefined,
  userId: string,
  purpose: 'pending' | 'enabled',
): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', encryptionKey(key), iv);
  cipher.setAAD(Buffer.from(`flowcredit:totp:v1:${userId}:${purpose}`));
  const data = Buffer.concat([cipher.update(secret, 'utf8'), cipher.final()]);
  return [
    'v1',
    iv.toString('base64url'),
    cipher.getAuthTag().toString('base64url'),
    data.toString('base64url'),
  ].join('.');
}
export function decryptTotp(
  encoded: string,
  key: string | undefined,
  userId: string,
  purpose: 'pending' | 'enabled',
): string {
  const resolvedKey = encryptionKey(key);
  try {
    const [version, iv, tag, ciphertext, extra] = encoded.split('.');
    if (
      version !== 'v1' ||
      extra !== undefined ||
      !iv ||
      !tag ||
      !ciphertext ||
      !/^[A-Za-z0-9_-]{16}$/.test(iv) ||
      !/^[A-Za-z0-9_-]{22}$/.test(tag) ||
      !/^[A-Za-z0-9_-]{43}$/.test(ciphertext)
    )
      throw new Error('Invalid encrypted secret');
    const decipher = createDecipheriv(
      'aes-256-gcm',
      resolvedKey,
      Buffer.from(iv, 'base64url'),
    );
    decipher.setAAD(Buffer.from(`flowcredit:totp:v1:${userId}:${purpose}`));
    decipher.setAuthTag(Buffer.from(tag, 'base64url'));
    const secret = Buffer.concat([
      decipher.update(Buffer.from(ciphertext, 'base64url')),
      decipher.final(),
    ]).toString('utf8');
    if (!/^[A-Z2-7]{32}$/.test(secret))
      throw new Error('Invalid decrypted secret');
    return secret;
  } catch {
    throw new ApiProblem(
      503,
      'Authenticator unavailable',
      'Authenticator verification is unavailable. Use an unused recovery code or your account recovery key.',
    );
  }
}
export const recoveryHash = (
  userId: string,
  code: string,
  purpose: 'mfa' | 'account',
) =>
  createHash('sha256')
    .update(`flowcredit:recovery:v1:${purpose}:${userId}:${code}`)
    .digest('hex');
export const newRecoveryCodes = () =>
  Array.from({ length: 10 }, () =>
    randomBytes(16).toString('hex').toUpperCase().match(/.{8}/g)!.join('-'),
  );
export function authenticatorUri(secret: string, email: string): string {
  const params = new URLSearchParams({
    secret,
    issuer: 'FlowCredit',
    algorithm: 'SHA1',
    digits: '6',
    period: '30',
  });
  return `otpauth://totp/${encodeURIComponent(`FlowCredit:${email}`)}?${params}`;
}
