/**
 * Fake session for the mockup.
 *
 * Any credentials are accepted and the "session" is a name in localStorage —
 * there is no token and no server. Replacing this with a real /auth call is
 * the only change the route guard should need.
 */

const STORAGE_KEY = 'cheap_recipe.session'

export interface Session {
  email: string
  signedInAt: string
}

export function getSession(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Session) : null
  } catch {
    // Private windows and blocked site data both throw here.
    return null
  }
}

export function signIn(email: string): Session {
  const session: Session = { email, signedInAt: new Date().toISOString() }
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
