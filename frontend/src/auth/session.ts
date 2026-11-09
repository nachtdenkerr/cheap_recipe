/**
 * Whether someone is signed in, as far as this tab knows — so a reload
 * renders the app instead of the login page while Neon Auth's own session
 * (a cookie on the Auth URL, src/auth/neonAuth.ts) is checked by the first
 * request. Only the email is kept, for the account menu; no token is stored.
 *
 * An expired or ended Neon Auth session makes the API answer 401, and the
 * HTTP client then signs out here too.
 */

import { endSession } from './neonAuth'

const STORAGE_KEY = 'cheap_recipe.session'

export interface Session {
  email: string
  signedInAt: string
}

export function getSession(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const session = raw ? (JSON.parse(raw) as Partial<Session>) : null
    // A session from before Neon Auth carried the old API token: signed out.
    return session?.email && !('token' in session) ? (session as Session) : null
  } catch {
    // Private windows and blocked site data both throw here.
    return null
  }
}

export function saveSession(email: string): Session {
  const session: Session = { email, signedInAt: new Date().toISOString() }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
  } catch {
    // Fall through — the session just won't survive a reload.
  }
  return session
}

export function signOut(): void {
  void endSession()
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Nothing to do.
  }
}
