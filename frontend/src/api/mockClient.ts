/**
 * The mock backend: the same functions as httpClient.ts, answered from
 * mockData.ts in memory. Used when VITE_USE_MOCK=true, so the UI can be worked
 * on without the API running. State resets on reload.
 */

import { ApiError } from './errors'
import { extraRecipes, markets, recipes, user } from './mockData'
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

/** The mock offers' week (see mockData.ts), for "From Thursday" pills. */
export const OFFER_WEEK_START = '2025-11-17'

/** Any email and password sign in; nothing leaves the browser. */
export function login(email: string, _password: string): Promise<AuthSession> {
  return resolve({ token: 'mock-token', user: { ...user, email } })
}

export function signup(request: SignupRequest): Promise<AuthSession> {
  return login(request.email, request.password)
}

/** Ticks are kept by the page in the mock; nothing to save. */
export function setChecked(_id: number, _checked: boolean): Promise<void> {
  return resolve(undefined)
}

export function uncheckAll(): Promise<void> {
  return resolve(undefined)
}

/** Pretend network latency, so loading states are actually visible. */
const LATENCY_MS = 250

function resolve<T>(value: T): Promise<T> {
  return new Promise((done) => setTimeout(() => done(value), LATENCY_MS))
}

const WEEK = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']
const MAX_DAYS_PER_COOKING = 3

/**
 * GET /mealplan — the meal plan's recipes placed Monday to Friday, as
 * backend/src/cheaprecipe/calculation/schedule.py does it: one cooking feeds
 * servings ÷ household meals, on following days, at most three.
 */
export function fetchWeekPlan(): Promise<WeekPlan> {
  const meals = (['breakfast', 'lunch', 'dinner'] as const).filter((m) => user.mealTypes.includes(m))
  const grid = WEEK.map(() => new Map(meals.map((m) => [m, null as null | { id: string; title: string; leftover: boolean }])))
  const spare: WeekPlan['spare'] = []
  const planned = recipes.filter((r) => r.inMealPlan)
  const slotsFor = (course?: string) =>
    course === 'breakfast' && meals.includes('breakfast')
      ? (['breakfast'] as const)
      : meals.filter((m) => m !== 'breakfast')
  const place = (recipe: (typeof planned)[number], days: number[], leftover: boolean, latestFirst = false) => {
    const order = latestFirst ? [...slotsFor(recipe.course)].reverse() : slotsFor(recipe.course)
    for (const day of days) {
      const meal = order.find((m) => grid[day].get(m) === null)
      if (meal) {
        grid[day].set(meal, { id: recipe.id, title: recipe.title, leftover })
        return day
      }
    }
    return null
  }
  // As schedule.py: each recipe cooked once first, spread over the week at
  // dinner; then leftovers on the following days, within three days.
  const cooked = new Map<string, number>()
  const isBreakfast = (r: (typeof planned)[number]) => slotsFor(r.course)[0] === 'breakfast'
  for (const group of [planned.filter(isBreakfast), planned.filter((r) => !isBreakfast(r))]) {
    group.forEach((recipe, rank) => {
      const start = group.length <= WEEK.length ? Math.floor((rank * WEEK.length) / group.length) : rank % WEEK.length
      const order = [...WEEK.keys()].slice(start).concat([...WEEK.keys()].slice(0, start))
      const day = place(recipe, order, false, true)
      if (day !== null) cooked.set(recipe.id, day)
    })
  }
  for (const recipe of planned) {
    const made = Math.max(1, Math.floor(recipe.servings / user.householdSize))
    let placed = 0
    const first = cooked.get(recipe.id)
    if (first !== undefined) {
      placed = 1
      let last = first
      while (placed < made) {
        const window = [...WEEK.keys()].filter((d) => d > last && d < first + MAX_DAYS_PER_COOKING)
        const day = place(recipe, window, true)
        if (day === null) break
        placed += 1
        last = day
      }
    }
    if (made > placed) spare.push({ recipeId: recipe.id, title: recipe.title, portions: made - placed })
  }
  const monday = new Date(`${OFFER_WEEK_START}T00:00:00`)
  const days = WEEK.map((day, index) => {
    const date = new Date(monday)
    date.setDate(monday.getDate() + index)
    return {
      day,
      date: date.toISOString().slice(0, 10),
      meals: meals.map((meal) => {
        const slot = grid[index].get(meal)
        return { meal, recipeId: slot?.id ?? null, title: slot?.title ?? null, leftover: slot?.leftover ?? false }
      }),
    }
  })
  const emptyMeals = days.reduce((n, d) => n + d.meals.filter((m) => !m.recipeId).length, 0)
  return resolve({ mealTypes: [...meals], householdSize: user.householdSize, days, emptyMeals, spare })
}

/** GET /markets — by name, street, town or postcode. */
export function searchMarkets(query: string): Promise<Market[]> {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  return resolve(
    markets.filter((market) => {
      const text = [market.name, market.street, market.postalCode, market.city].join(' ').toLowerCase()
      return words.every((word) => text.includes(word))
    }),
  )
}

/** GET /recipes — the recipes the agent loop produced for this week's offers. */
export function fetchRecipes(): Promise<Recipe[]> {
  return resolve(recipes)
}

/** GET /recipes/{id} */
export function fetchRecipe(id: string): Promise<Recipe | undefined> {
  return resolve(recipes.find((recipe) => recipe.id === id))
}

/** Mock-only: a stable id per shopping line, as generation_item rows give. */
const lineIds = new Map<string, number>()
function lineId(key: string): number {
  if (!lineIds.has(key)) lineIds.set(key, lineIds.size + 1)
  return lineIds.get(key)!
}

/**
 * GET /shopping — everything the meal plan needs except pantry staples: one
 * line per offer, then one per ingredient bought at the regular price. The
 * mock derives it here the way the server does.
 */
export function fetchShoppingList(): Promise<ShoppingListItem[]> {
  const offerLines = new Map<string, ShoppingListItem>()
  const regularLines = new Map<string, ShoppingListItem>()
  for (const recipe of recipes.filter((r) => r.inMealPlan)) {
    for (const ingredient of recipe.ingredients) {
      if (ingredient.pantry) continue
      const { offer } = ingredient
      const key = offer ? `offer:${offer.title}` : `name:${ingredient.name}`
      const lines = offer ? offerLines : regularLines
      const line = lines.get(key)
      if (line) {
        if (!line.usedBy.includes(recipe.title)) line.usedBy.push(recipe.title)
        if (!offer) line.amount = `${line.amount}, ${ingredient.amount}`
        continue
      }
      lines.set(key, {
        id: lineId(key),
        name: offer ? (offer.ingredientEn ?? offer.title) : ingredient.name,
        offer: offer ?? null,
        amount: offer ? null : ingredient.amount,
        quantity: 1,
        estimatedPriceCents: offer ? null : (ingredient.regularPriceCents ?? null),
        usedBy: [recipe.title],
        checked: false,
      })
    }
  }
  return resolve([...offerLines.values(), ...regularLines.values()])
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
  const { homeMarketIds, ...rest } = changes
  Object.assign(user, rest)
  if (homeMarketIds) {
    user.homeMarkets = homeMarketIds.flatMap((id) => markets.filter((m) => m.id === id))
  }
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
