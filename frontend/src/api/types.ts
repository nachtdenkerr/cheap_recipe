/**
 * Shapes the backend is expected to return.
 *
 * These mirror the pipeline: an `Offer` is one normalized EDEKA item
 * (ingestion + normalization), a `Recipe` is what the agent loop produces once
 * `calculation/` has costed it, and a `ShoppingListItem` is the offer-level
 * view of everything a set of recipes needs.
 *
 * Money is in euro cents to keep arithmetic exact — format with formatPrice().
 */

import type { Allergen, DietType } from './vocabulary'

export type { Allergen, DietType }

export interface Offer {
  /** Original German product name, as printed in the shop. */
  title: string
  /** Normalized English ingredient, from normalization/ingredients.py. */
  ingredientEn: string
  category: string
  priceCents: number
  /** ISO dates — offers are only valid for part of the week. */
  validFrom: string
  validTill: string
  dietType: DietType
}

export interface RecipeIngredient {
  /** English ingredient name as it appears in the recipe. */
  name: string
  /** Human-readable amount, e.g. "400 g" or "2 tbsp". */
  amount: string
  /** The discounted offer this maps to, when the recipe is built on one. */
  offer?: Offer
  /** True when the user is assumed to have it already (salt, oil, flour). */
  pantry?: boolean
}

export interface Nutrition {
  /** Per serving. */
  kcal: number
  proteinG: number
  carbsG: number
  fatG: number
}

export interface RecipeCost {
  /** Cost of the ingredients actually used by this recipe. */
  totalCents: number
  perServingCents: number
  /** Value of the part of each pack the recipe does not use. */
  leftoverCents: number
}

export interface Recipe {
  id: string
  title: string
  summary: string
  servings: number
  minutes: number
  dietType: DietType
  /** Allergens present, from the deterministic allergen filter. */
  allergens: string[]
  ingredients: RecipeIngredient[]
  steps: string[]
  cost: RecipeCost
  nutrition: Nutrition
  /** Why the planner chose this — surfaced so the ranking stays explainable. */
  rationale: string
  /** Hearted by the user; saved on their preferences. */
  isFavourite: boolean
  /** Chosen for this week — only these recipes fill the shopping list. */
  inMealPlan: boolean
}

export interface ShoppingListItem {
  offer: Offer
  /** How many packs to buy. */
  quantity: number
  /** Titles of the recipes that need this item. */
  usedBy: string[]
  checked: boolean
}

/** The account plus its preferences — mirrors user_preference in the database. */
export interface User {
  name: string
  email: string
  dietType: DietType
  householdSize: number
  /** Null when no budget is set. */
  weeklyBudgetCents: number | null
  /** Allergens to exclude — fed to the allergen filter, never to the LLM. */
  allergens: Allergen[]
  /** Chain name of the home supermarket, e.g. "EDEKA". */
  market: string | null
  cuisines: string[]
  /** Ingredients to favour when planning. */
  whiteList: string[]
  /** Ingredients not allergic to, but not wanted either. */
  blackList: string[]
  age: number | null
  gender: string | null
}

/** Body of POST /auth/me/preferences — only the fields sent are changed. */
export type PreferencesUpdate = Partial<
  Pick<
    User,
    | 'name'
    | 'dietType'
    | 'householdSize'
    | 'weeklyBudgetCents'
    | 'allergens'
    | 'market'
    | 'cuisines'
    | 'whiteList'
    | 'blackList'
    | 'age'
    | 'gender'
  >
>

/** Body of POST /generate/refine. Each request uses one of the week's quota. */
export interface RefineRequest {
  /** "replace": swap the unplanned recipes; "pantry": favour fridge items. */
  mode: 'replace' | 'pantry'
  /** How many new recipes; the server defaults to the number of unplanned ones. */
  count?: number
  pantryItems?: string[]
  /** Free text for the AI planner, e.g. "nothing spicy". */
  note?: string
}

/** GET /generate/quota */
export interface RefineQuota {
  used: number
  limit: number
  remaining: number
  /** ISO timestamp — next Monday 00:00, German time. */
  resetsAt: string
  /** False until this week's first plan exists. */
  weeklyPlanDone: boolean
}

export interface RefineResponse {
  recipes: Recipe[]
  quota: RefineQuota
}
