export function readInvitationToken() {
  const hash = window.location.hash.slice(1);
  if (!hash.startsWith('invite')) return '';
  return new URLSearchParams(hash.split('?')[1]).get('token') ?? '';
}
