import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  authenticatorUri,
  decodeBase32,
  decryptTotp,
  encodeBase32,
  encryptTotp,
  hotp,
  newRecoveryCodes,
  newTotpSecret,
  recoveryHash,
  totpCounter,
} from './account-security.js';
import { ApiProblem } from './problem.js';

test('HOTP and TOTP match the independent RFC 4226/6238 SHA1 vectors', () => {
  const secret = encodeBase32(Buffer.from('12345678901234567890'));
  const values = [
    '755224',
    '287082',
    '359152',
    '969429',
    '338314',
    '254676',
    '287922',
    '162583',
    '399871',
    '520489',
  ];
  values.forEach((value, counter) =>
    assert.equal(hotp(secret, counter), value),
  );
  for (const [time, expected] of [
    [59, '94287082'],
    [1111111109, '07081804'],
    [1111111111, '14050471'],
    [1234567890, '89005924'],
    [2000000000, '69279037'],
    [20000000000, '65353130'],
  ] as const)
    assert.equal(hotp(secret, Math.floor(time / 30), 8), expected);
});
test('base32 secrets are random, canonical and compatible with authenticator URI parameters', () => {
  const first = newTotpSecret(),
    second = newTotpSecret();
  assert.match(first, /^[A-Z2-7]{32}$/);
  assert.notEqual(first, second);
  assert.equal(decodeBase32(first).length, 20);
  assert.equal(encodeBase32(decodeBase32(first)), first);
  assert.throws(() => decodeBase32('AB'));
  assert.throws(() => decodeBase32('INVALID='));
  const uri = new URL(authenticatorUri(first, 'officer+team@example.test'));
  assert.equal(uri.protocol, 'otpauth:');
  assert.equal(uri.searchParams.get('secret'), first);
  assert.equal(uri.searchParams.get('issuer'), 'FlowCredit');
  assert.equal(uri.searchParams.get('period'), '30');
});
test('TOTP accepts only the narrow clock window and refuses consumed counters', () => {
  const secret = newTotpSecret(),
    now = 1234567890000,
    counter = Math.floor(now / 30000);
  assert.equal(totpCounter(secret, hotp(secret, counter), null, now), counter);
  assert.equal(
    totpCounter(secret, hotp(secret, counter - 1), null, now),
    counter - 1,
  );
  assert.equal(
    totpCounter(secret, hotp(secret, counter + 1), null, now),
    counter + 1,
  );
  assert.equal(totpCounter(secret, hotp(secret, counter - 2), null, now), null);
  assert.equal(totpCounter(secret, hotp(secret, counter), counter, now), null);
  assert.equal(
    totpCounter(secret, hotp(secret, counter - 1), counter, now),
    null,
  );
  assert.equal(totpCounter(secret, '000', null, now), null);
});
test('AES-GCM secrets bind account and state and fail closed for missing/wrong keys or tampering', () => {
  const secret = newTotpSecret(),
    key = '1'.repeat(64);
  const encrypted = encryptTotp(secret, key, 'user-a', 'pending');
  assert.notEqual(encrypted, encryptTotp(secret, key, 'user-a', 'pending'));
  assert.ok(!encrypted.includes(secret));
  assert.equal(decryptTotp(encrypted, key, 'user-a', 'pending'), secret);
  for (const attempt of [
    () => encryptTotp(secret, undefined, 'user-a', 'pending'),
    () => decryptTotp(encrypted, undefined, 'user-a', 'pending'),
    () => decryptTotp(encrypted, '2'.repeat(64), 'user-a', 'pending'),
    () => decryptTotp(encrypted, key, 'user-b', 'pending'),
    () => decryptTotp(encrypted, key, 'user-a', 'enabled'),
    () => decryptTotp(`${encrypted.slice(0, -2)}AA`, key, 'user-a', 'pending'),
  ])
    assert.throws(
      attempt,
      (error) => error instanceof ApiProblem && error.status === 503,
    );
});
test('recovery codes have independent 128-bit entropy and hashes bind account and purpose', () => {
  const codes = newRecoveryCodes();
  assert.equal(codes.length, 10);
  assert.equal(new Set(codes).size, 10);
  for (const code of codes)
    assert.match(code, /^[A-F0-9]{8}(?:-[A-F0-9]{8}){3}$/);
  const hash = recoveryHash('user-a', codes[0]!, 'mfa');
  assert.match(hash, /^[a-f0-9]{64}$/);
  assert.notEqual(hash, recoveryHash('user-b', codes[0]!, 'mfa'));
  assert.notEqual(hash, recoveryHash('user-a', codes[0]!, 'account'));
});
