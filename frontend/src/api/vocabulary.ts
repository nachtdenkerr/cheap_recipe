/**
 * The choices a user can pick from. Kept in step with CommonDiet and Allergen
 * in backend/src/cheaprecipe/vocabulary.py — the API rejects anything else.
 */

export const DIETS = ['normal', 'vegetarian', 'vegan', 'pescetarian'] as const
export type DietType = (typeof DIETS)[number]

/** The 14 allergens EU food labels must declare. "nuts" means tree nuts. */
export const ALLERGENS = [
  'gluten',
  'crustaceans',
  'eggs',
  'fish',
  'peanuts',
  'soy',
  'milk',
  'nuts',
  'celery',
  'mustard',
  'sesame',
  'sulphites',
  'lupin',
  'molluscs',
] as const
export type Allergen = (typeof ALLERGENS)[number]

export const WEEKDAYS = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
] as const
export type Weekday = (typeof WEEKDAYS)[number]

/** Cooking time per day, 0 (no cooking) to 24 h in 15-minute steps — as the API accepts. */
export const DAY_MINUTE_OPTIONS = Array.from({ length: (24 * 60) / 15 + 1 }, (_, i) => i * 15)

/** What a day starts at when the user first sets their week. */
export const DEFAULT_DAY_MINUTES = 60
