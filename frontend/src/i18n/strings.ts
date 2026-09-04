/**
 * All user-facing copy.
 *
 * English is the only locale for now; adding German means adding a second
 * dictionary with the same keys and switching `locale`. Keeping the strings out
 * of the components is the whole point — nothing else should hold literal copy.
 */

export const en = {
  appName: 'cheap_recipe',
  tagline: 'This week’s discounts, turned into dinner.',

  nav: {
    home: 'Recipes',
    shoppingList: 'Shopping list',
    profile: 'Profile',
    signOut: 'Sign out',
  },

  login: {
    heading: 'Welcome back',
    subheading: 'Sign in to see what this week’s offers can cook.',
    email: 'Email',
    password: 'Password',
    emailPlaceholder: 'you@example.com',
    submit: 'Sign in',
    mockNotice:
      'Mockup: any email and password will sign you in. No account is created and nothing leaves your browser.',
    emailRequired: 'Enter an email address to continue.',
    passwordRequired: 'Enter a password to continue.',
  },

  home: {
    heading: 'Recipes for this week',
    subheading: (count: number, from: string, till: string) =>
      `${count} recipes built from offers valid ${from} – ${till}.`,
    regenerate: 'Regenerate',
    regenerating: 'Asking the planner…',
    totalCost: 'Basket total',
    totalSaving: 'You save',
    perServing: 'per serving',
    servings: (n: number) => `${n} servings`,
    minutes: (n: number) => `${n} min`,
    viewRecipe: 'View recipe',
    empty: 'No recipes yet. Run the planner to build some from this week’s offers.',
  },

  recipe: {
    back: 'Back to recipes',
    ingredients: 'Ingredients',
    method: 'Method',
    onOffer: 'on offer',
    pantry: 'from your pantry',
    whyThis: 'Why the planner picked this',
    costBreakdown: 'Cost',
    recipeTotal: 'Recipe total',
    regularPrice: 'At regular prices',
    leftoverValue: 'Unused leftovers',
    nutrition: 'Nutrition per serving',
    kcal: 'Calories',
    protein: 'Protein',
    carbs: 'Carbs',
    fat: 'Fat',
    allergens: 'Contains',
    allergenFree: 'No common allergens',
    availableFrom: (date: string) => `From ${date}`,
    notFound: 'That recipe doesn’t exist.',
  },

  shopping: {
    heading: 'Shopping list',
    subheading: (items: number, recipes: number) =>
      `${items} items covering ${recipes} recipes.`,
    remaining: 'Still to buy',
    inBasket: 'In the basket',
    total: 'Total',
    checkedTotal: 'Collected',
    usedBy: 'For',
    clearChecked: 'Uncheck all',
    empty: 'Nothing to buy — pick some recipes first.',
  },

  profile: {
    heading: 'Profile',
    preferences: 'Preferences',
    diet: 'Diet',
    household: 'Household size',
    householdValue: (n: number) => `${n} people`,
    budget: 'Weekly budget',
    allergens: 'Allergens to avoid',
    noAllergens: 'None set',
    market: 'Home market',
    thisWeek: 'This week',
    recipesPlanned: 'Recipes planned',
    basketTotal: 'Basket total',
    saved: 'Saved vs. regular prices',
    mockNotice: 'Mockup: these preferences are read-only until the backend is wired up.',
  },

  diet: {
    vegan: 'Vegan',
    vegetarian: 'Vegetarian',
    normal: 'No restrictions',
  },

  common: {
    loading: 'Loading…',
  },
} as const

export type Strings = typeof en

/** Swap for a German dictionary once one exists. */
export const t = en
