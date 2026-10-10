import type { AuthSession } from '@wiut/contracts';
export interface AuthContext extends AuthSession {
  session_hash: string;
}
