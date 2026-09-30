/**
 * The single seam between the UI and the backend.
 *
 * Components import from here and nowhere else. By default this is the real
 * API (httpClient.ts); with VITE_USE_MOCK=true in .env.local it is the
 * in-memory mock (mockClient.ts), for working on the UI without a backend.
 * Both expose the same functions with the same types.
 */

import * as http from './httpClient'
import * as mock from './mockClient'

export { ApiError } from './errors'

export const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

const api: typeof http = USE_MOCK ? mock : http

export const {
  OFFER_WEEK_START,
  login,
  signup,
  fetchUser,
  savePreferences,
  searchMarkets,
  fetchRecipes,
  fetchRecipe,
  setFavourite,
  setInMealPlan,
  fetchShoppingList,
  setChecked,
  uncheckAll,
  planWeek,
  fetchWeekPlan,
  fetchRefineQuota,
  fetchPlanReview,
  startWeeklyPlan,
  startRecipeRequest,
  fetchPlanningJob,
  requestRecipes,
} = api
