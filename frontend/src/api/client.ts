/**
 * The single seam between the UI and the backend.
 *
 * Everything is async and typed as the real endpoints will be, so switching to
 * FastAPI means replacing the bodies here — no component changes. The routes
 * each function will call are named in its comment.
 */

import { recipes, shoppingList, user } from './mockData'
import type { Recipe, ShoppingListItem, User } from './types'

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

/** GET /shopping — offer-level list covering every selected recipe. */
export function fetchShoppingList(): Promise<ShoppingListItem[]> {
  return resolve(shoppingList)
}

/** GET /auth/me */
export function fetchUser(): Promise<User> {
  return resolve(user)
}

/** POST /generate — rerun the agent loop against the current offers. */
export function regenerateRecipes(): Promise<Recipe[]> {
  return resolve(recipes)
}
