/**
 * Neon Auth (Managed Better Auth): signing up, in and out, and the JWT the
 * API checks on every request (backend/app/security.py).
 *
 * The browser talks to the branch's Auth URL directly; its session cookie
 * never reaches the API. What the API and the `live` function get is the
 * session's short-lived JWT (about 15 minutes), as `Authorization: Bearer`.
 */

import { createAuthClient } from '@neon/auth'

import { ApiError } from '../api/errors'

const AUTH_URL = import.meta.env.VITE_NEON_AUTH_URL

const makeClient = (url: string) => createAuthClient(url)
let client: ReturnType<typeof makeClient> | null = null

function auth() {
  if (!AUTH_URL) {
    throw new ApiError(0, 'Neon Auth is not configured (VITE_NEON_AUTH_URL)')
  }
  client ??= makeClient(AUTH_URL)
  return client
}

interface AuthErrorLike {
  status?: number
  message?: string
  code?: string
}

function toApiError(error: AuthErrorLike | null | undefined, fallback: string): ApiError {
  return new ApiError(error?.status ?? 500, error?.message || error?.code || fallback)
}

/**
 * The current session's JWT, or null when nobody is signed in. The Neon
 * wrapper puts the JWT in `session.token` and caches the session until the
 * token is about to expire, so this is cheap to call before every request.
 */
export async function getToken(): Promise<string | null> {
  try {
    const { data } = await auth().getSession()
    return data?.session?.token ?? null
  } catch {
    return null
  }
}

export async function signIn(email: string, password: string): Promise<void> {
  const { error } = await auth().signIn.email({ email, password })
  if (error) throw toApiError(error, 'Sign-in failed')
}

export async function signUp(email: string, password: string, name: string): Promise<void> {
  const { error } = await auth().signUp.email({ email, password, name })
  if (error) throw toApiError(error, 'Sign-up failed')
}

export async function endSession(): Promise<void> {
  try {
    await auth().signOut()
  } catch {
    // Signed out locally either way.
  }
}
