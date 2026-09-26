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
