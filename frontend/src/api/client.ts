/**
 * The single seam between the UI and the backend.
 *
 * Everything is async and typed as the real endpoints will be, so switching to
 * FastAPI means replacing the bodies here — no component changes. The routes
 * each function will call are named in its comment.
 */

import { extraRecipes, recipes, user } from './mockData'
import type {
  PreferencesUpdate,
  Recipe,
  RefineQuota,
  RefineRequest,
  RefineResponse,
  ShoppingListItem,
  User,
} from './types'

/** A failed request, with the HTTP status the real API would have answered. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

/** Pretend network latency, so loading states are actually visible. */
const LATENCY_MS = 250

function resolve<T>(value: T): Promise<T> {
  return new Promise((done) => setTimeout(() => done(value), LATENCY_MS))
}

/** GET /recipes — the recipes the agent loop produced for this week's offers. */
export function fetchRecipes(): Promise<Recipe[]> {
  return resolve(recipes)
}

/** GET /recipes/{id} */
export function fetchRecipe(id: string): Promise<Recipe | undefined> {
  return resolve(recipes.find((recipe) => recipe.id === id))
}

/**
 * GET /shopping — one line per offer, covering only the recipes in the meal
 * plan. The mock derives it here the way the server does.
 */
export function fetchShoppingList(): Promise<ShoppingListItem[]> {
  const lines = new Map<string, ShoppingListItem>()
  for (const recipe of recipes.filter((r) => r.inMealPlan)) {
    for (const { offer } of recipe.ingredients) {
      if (!offer) continue
      const line = lines.get(offer.title)
      if (line) {
        if (!line.usedBy.includes(recipe.title)) line.usedBy.push(recipe.title)
      } else {
        lines.set(offer.title, {
          offer,
          quantity: 1,
          usedBy: [recipe.title],
          checked: false,
        })
      }
    }
  }
  return resolve([...lines.values()])
}

function updateRecipe(id: string, changes: Partial<Recipe>): Promise<Recipe> {
  const recipe = recipes.find((r) => r.id === id)
  if (!recipe) return Promise.reject(new Error(`No recipe ${id}`))
  Object.assign(recipe, changes)
  return resolve({ ...recipe })
}

/** POST /recipes/{id}/favourite to heart, DELETE to unheart. */
export function setFavourite(id: string, favourite: boolean): Promise<Recipe> {
  return updateRecipe(id, { isFavourite: favourite })
}

/** POST /recipes/{id}/meal-plan to add, DELETE to remove. */
export function setInMealPlan(id: string, inMealPlan: boolean): Promise<Recipe> {
  return updateRecipe(id, { inMealPlan })
}

/** GET /auth/me */
export function fetchUser(): Promise<User> {
  return resolve(user)
}

/**
 * POST /auth/me/preferences — send only what changed; resolves to the updated
 * user. The server trims, lower-cases and de-duplicates ingredient lists, so
 * the mock does the same.
 */
export function savePreferences(changes: PreferencesUpdate): Promise<User> {
  const clean = (names: string[]) => [
    ...new Set(names.map((name) => name.trim().toLowerCase()).filter(Boolean)),
  ]
  Object.assign(user, changes)
  if (changes.whiteList) user.whiteList = clean(changes.whiteList)
  if (changes.blackList) user.blackList = clean(changes.blackList)
  return resolve({ ...user })
}

/** POST /generate — the week's first plan. Free, once per week. */
export function planWeek(): Promise<Recipe[]> {
  return resolve(recipes.map((recipe) => ({ ...recipe })))
}

// --- mock state for recipe requests ------------------------------------------

const REFINES_PER_WEEK = 2
let refinesUsed = 0
/** Recipes shown this week, so a request never brings one back. */
const seen = new Set(recipes.map((recipe) => recipe.id))

function nextMonday(): string {
  const date = new Date()
  date.setHours(0, 0, 0, 0)
  date.setDate(date.getDate() + ((8 - date.getDay()) % 7 || 7))
  return date.toISOString()
}

function quota(): RefineQuota {
  return {
    used: refinesUsed,
    limit: REFINES_PER_WEEK,
    remaining: Math.max(REFINES_PER_WEEK - refinesUsed, 0),
    resetsAt: nextMonday(),
    weeklyPlanDone: true,
  }
}

/** GET /generate/quota */
export function fetchRefineQuota(): Promise<RefineQuota> {
  return resolve(quota())
}

/**
 * POST /generate/refine — keep the planned recipes, replace the rest.
 *
 * The mock draws from `extraRecipes`; in fridge mode it puts first the ones
 * whose ingredients mention a fridge item, as the planner prefers them.
 */
export async function requestRecipes(request: RefineRequest): Promise<RefineResponse> {
  if (refinesUsed >= REFINES_PER_WEEK) {
    await resolve(undefined)
    throw new ApiError(429, 'No recipe requests left this week')
  }

  const planned = recipes.filter((recipe) => recipe.inMealPlan)
  const count = request.count ?? Math.max(recipes.length - planned.length, 1)
  const pantry = (request.pantryItems ?? []).map((item) => item.toLowerCase())
  const usesPantry = (recipe: Recipe) =>
    recipe.ingredients.some((i) => pantry.some((item) => i.name.toLowerCase().includes(item)))

  const fresh = extraRecipes
    .filter((recipe) => !seen.has(recipe.id))
    .sort((a, b) => Number(usesPantry(b)) - Number(usesPantry(a)))
    .slice(0, count)
  if (fresh.length === 0) {
    await resolve(undefined)
    throw new ApiError(409, 'No new recipes fit this week’s offers')
  }

  fresh.forEach((recipe) => seen.add(recipe.id))
  recipes.splice(0, recipes.length, ...planned, ...fresh)
  refinesUsed += 1
  return resolve({ recipes: recipes.map((recipe) => ({ ...recipe })), quota: quota() })
}
