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

export type DietType = 'vegan' | 'vegetarian' | 'normal'

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
  /** What the same basket would cost at non-discounted prices. */
  regularTotalCents: number
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
}

export interface ShoppingListItem {
  offer: Offer
  /** How many packs to buy. */
  quantity: number
  /** Titles of the recipes that need this item. */
  usedBy: string[]
  checked: boolean
}

export interface User {
  name: string
  email: string
  dietType: DietType
  householdSize: number
  weeklyBudgetCents: number
  /** Allergens to exclude — fed to the allergen filter, never to the LLM. */
  allergens: string[]
  market: string
}
