/**
 * The real backend: the FastAPI app in backend/app, reached through Vite's
 * /api proxy in development (vite.config.ts) or VITE_API_URL in a build.
 *
 * Every function mirrors one route; the response shapes are app/schemas,
 * camelCase on the wire, and match ./types.ts.
 */

import { getSession, signOut } from '../auth/session'
import { ApiError } from './errors'
import type {
  AuthSession,
  Market,
  PreferencesUpdate,
  Recipe,
  RefineQuota,
  RefineRequest,
  RefineResponse,
  ShoppingListItem,
  SignupRequest,
  User,
  WeekPlan,
} from './types'

const BASE_URL = import.meta.env.VITE_API_URL ?? '/api'

/** Monday of the current week — offers starting later get a "From …" pill. */
export const OFFER_WEEK_START = (() => {
  const day = new Date()
  day.setDate(day.getDate() - ((day.getDay() + 6) % 7))
  return [day.getFullYear(), day.getMonth() + 1, day.getDate()]
    .map((part) => String(part).padStart(2, '0'))
    .join('-')
})()

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const session = getSession()
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (session) headers.Authorization = `Bearer ${session.token}`

  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'The server could not be reached')
  }

  if (response.status === 401 && session) {
    // The token expired or was revoked: back to the login page.
    signOut()
    window.location.assign('/login')
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response))
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

/** FastAPI's `detail`: a string, or a list of validation errors. */
async function errorMessage(response: Response): Promise<string> {
  try {
    const { detail } = await response.json()
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg
  } catch {
    // Not JSON — fall back to the status text.
  }
  return response.statusText || `HTTP ${response.status}`
}

// --- auth -----------------------------------------------------------------------

export function login(email: string, password: string): Promise<AuthSession> {
  return request('POST', '/auth/login', { email, password })
}

export function signup(body: SignupRequest): Promise<AuthSession> {
  return request('POST', '/auth/signup', body)
}

export function fetchUser(): Promise<User> {
  return request('GET', '/auth/me')
}

export function savePreferences(changes: PreferencesUpdate): Promise<User> {
  return request('POST', '/auth/me/preferences', changes)
}

// --- markets --------------------------------------------------------------------

export function searchMarkets(query: string): Promise<Market[]> {
  return request('GET', `/markets?q=${encodeURIComponent(query)}`)
}

// --- recipes --------------------------------------------------------------------

export function fetchRecipes(): Promise<Recipe[]> {
  return request('GET', '/recipes')
}

export async function fetchRecipe(id: string): Promise<Recipe | undefined> {
  try {
    return await request<Recipe>('GET', `/recipes/${encodeURIComponent(id)}`)
  } catch (error) {
    // Not one of this user's recipes (or not a number at all).
    if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
      return undefined
    }
    throw error
  }
}

export function setFavourite(id: string, favourite: boolean): Promise<Recipe> {
  return request(favourite ? 'POST' : 'DELETE', `/recipes/${id}/favourite`)
}

export function setInMealPlan(id: string, inMealPlan: boolean): Promise<Recipe> {
  return request(inMealPlan ? 'POST' : 'DELETE', `/recipes/${id}/meal-plan`)
}

// --- shopping -------------------------------------------------------------------

export function fetchShoppingList(): Promise<ShoppingListItem[]> {
  return request('GET', '/shopping')
}

export async function setChecked(id: number, checked: boolean): Promise<void> {
  await request('PATCH', `/shopping/${id}`, { checked })
}

export function uncheckAll(): Promise<void> {
  return request('POST', '/shopping/uncheck-all')
}

// --- the week grid ------------------------------------------------------------

export function fetchWeekPlan(): Promise<WeekPlan> {
  return request('GET', '/mealplan')
}

// --- planning -------------------------------------------------------------------

export function planWeek(): Promise<Recipe[]> {
  return request('POST', '/generate')
}

export function fetchRefineQuota(): Promise<RefineQuota> {
  return request('GET', '/generate/quota')
}

export function requestRecipes(body: RefineRequest): Promise<RefineResponse> {
  return request('POST', '/generate/refine', body)
}
