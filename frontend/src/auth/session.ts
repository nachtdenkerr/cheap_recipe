/**
 * The signed-in session: the API's token, kept in localStorage so a reload
 * stays signed in. The token is what every request sends
 * (`Authorization: Bearer …`); the email is kept for the account menu.
 *
 * The token itself expires server-side (a week, app/security.py). An expired
 * or revoked one makes the API answer 401, and the HTTP client then signs out.
 */

const STORAGE_KEY = 'cheap_recipe.session'

export interface Session {
  token: string
  email: string
  signedInAt: string
}

export function getSession(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const session = raw ? (JSON.parse(raw) as Partial<Session>) : null
    // A session from before real sign-in has no token; treat it as signed out.
    return session?.token ? (session as Session) : null
  } catch {
    // Private windows and blocked site data both throw here.
    return null
  }
}

export function saveSession(token: string, email: string): Session {
  const session: Session = { token, email, signedInAt: new Date().toISOString() }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
  } catch {
    // Fall through — the session just won't survive a reload.
  }
  return session
}

export function signOut(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Nothing to do.
  }
}
