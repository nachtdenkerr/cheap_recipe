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

import type { Allergen, DietType, MealType } from './vocabulary'

export type { Allergen, DietType, MealType }

export interface Offer {
  /** The offer row; absent in the mock. */
  id?: number
  /** Original German product name, as printed in the shop. */
  title: string
  /** Normalized English ingredient, from normalization/ingredients.py. */
  ingredientEn: string | null
  /** The store's department, when the scrape had one. */
  category: string | null
  priceCents: number
  /** ISO dates — offers are only valid for part of the week. */
  validFrom: string | null
  validTill: string | null
  /** The offer side has no diet (see backend vocabulary.py); kept for the mock. */
  dietType?: DietType | null
  /** The branch it is offered at, e.g. "EDEKA Frank". */
  market?: string | null
}

/** A supermarket branch — GET /markets. Offers are per branch. */
export interface Market {
  /** Our id; what PreferencesUpdate.homeMarketIds refers to. */
  id: number
  chain: 'edeka' | 'aldi'
  /** The chain's own id for the branch. */
  marketId: string
  name: string
  street: string | null
  postalCode: string | null
  city: string | null
}

export interface RecipeIngredient {
  /** English ingredient name as it appears in the recipe. */
  name: string
  /** Human-readable amount, e.g. "400 g" or "2 tbsp". */
  amount: string
  /** The discounted offer this maps to, when the recipe is built on one. */
  offer?: Offer
  /** Assumed at home: salt, pepper, sugar, oil, garlic. Not bought, not priced. */
  pantry?: boolean
  /**
   * Neither an offer nor pantry: bought at the regular price. This is the
   * estimated shelf price of the pack it comes in, or null when no typical
   * price is known (then the line counts towards unpricedCount).
   */
  regularPriceCents?: number | null
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
  /** The part of totalCents estimated at regular prices — shown as "≈ …" when above 0. */
  estimatedCents: number
  /**
   * Ingredients to buy with no price at all, not even an estimate. When above
   * 0 the totals are a floor — shown as "from …".
   */
  unpricedCount: number
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
  /** Eaten as a breakfast; otherwise at lunch or dinner. Absent in the mock. */
  course?: 'breakfast' | 'main'
}

/**
 * One thing to buy — pantry staples never appear. With `offer` it is on sale;
 * without, it is bought at the regular price, estimated when known.
 */
export interface ShoppingListItem {
  /** The generation_item row, so a tick can be saved. */
  id: number
  name: string
  offer?: Offer | null
  /** For a line that is not an offer: how much the recipes need ("700 g"). */
  amount?: string | null
  /** How many packs to buy. */
  quantity: number
  /** Not on offer: estimated price for `quantity` packs, or null when unknown. */
  estimatedPriceCents?: number | null
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
  /** Where the user shops; plans use these branches' offers. None: no plan. */
  homeMarkets: Market[]
  cuisines: string[]
  /** Ingredients to favour when planning. */
  whiteList: string[]
  /** Ingredients not allergic to, but not wanted either. */
  blackList: string[]
  age: number | null
  gender: string | null
  /** Minutes free for cooking each day, Monday first; null until set. */
  weekTimeAvailability: number[] | null
  /** Which meals of the day the week plan covers, in the day's order. */
  mealTypes: MealType[]
}

/** Body of POST /auth/me/preferences — only the fields sent are changed. */
export type PreferencesUpdate = { homeMarketIds?: number[] } & Partial<
  Pick<
    User,
    | 'name'
    | 'dietType'
    | 'householdSize'
    | 'weeklyBudgetCents'
    | 'allergens'
    | 'cuisines'
    | 'whiteList'
    | 'blackList'
    | 'age'
    | 'gender'
    | 'weekTimeAvailability'
    | 'mealTypes'
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

/** One meal of a day in GET /mealplan; no recipe means nothing is planned. */
export interface PlannedMeal {
  meal: MealType
  recipeId: string | null
  title: string | null
  /** Cooked on an earlier day, eaten again. */
  leftover: boolean
}

export interface PlanDay {
  /** "monday" … "friday" */
  day: string
  /** ISO date */
  date: string
  meals: PlannedMeal[]
}

/** GET /mealplan — the recipes in the meal plan, placed Monday to Friday. */
export interface WeekPlan {
  mealTypes: MealType[]
  householdSize: number
  days: PlanDay[]
  emptyMeals: number
  /** Portions the week has no meal for. */
  spare: { recipeId: string; title: string; portions: number }[]
}

/** POST /auth/login and /auth/signup */
export interface AuthSession {
  token: string
  user: User
}

export interface SignupRequest {
  username: string
  email: string
  password: string
  name?: string
}
