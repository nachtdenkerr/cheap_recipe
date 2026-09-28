/**
 * All user-facing copy.
 *
 * English is the only locale for now; adding German means adding a second
 * dictionary with the same keys and switching `locale`. Keeping the strings out
 * of the components is the whole point — nothing else should hold literal copy.
 */

export const en = {
  appName: 'CheapRecipe',
  tagline: 'This week’s discounts, turned into dinner.',

  nav: {
    home: 'Recipes',
    shoppingList: 'Shopping list',
    profile: 'Your profile',
    signOut: 'Sign out',
    accountMenu: 'Account menu',
    signedInAs: 'Signed in as',
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
    planWeek: 'Plan my week',
    planning: 'Planning…',
    askForRecipes: 'Ask for new recipes',
    requestsLeft: (n: number) => `${n} left`,
    resetsOn: (day: string) => `No requests left — resets ${day}`,
    newBadge: 'New',
    totalCost: 'Meal plan total',
    plannedCount: 'In your meal plan',
    addToPlan: 'Add to meal plan',
    inPlan: 'In meal plan',
    removeFromPlan: 'Remove from meal plan',
    favourite: (title: string) => `Save ${title} to favourites`,
    unfavourite: (title: string) => `Remove ${title} from favourites`,
    perServing: 'per serving',
    servings: (n: number) => `${n} servings`,
    minutes: (n: number) => `${n} min`,
    viewRecipe: 'View recipe',
    empty: 'No recipes yet. Run the planner to build some from this week’s offers.',
  },

  request: {
    heading: 'Ask for new recipes',
    intro: 'Recipes you added to your meal plan stay. The others are swapped for new ones.',
    whatDoYouNeed: 'What do you need?',
    replace: (n: number) => (n > 0 ? `Replace the ${n} I didn’t pick` : 'Get more recipes'),
    pantry: 'Use what’s in my fridge',
    pantryLabel: 'In my fridge',
    pantryHint: 'New recipes will use these where they can.',
    count: 'How many new recipes',
    note: 'Anything else? (optional)',
    notePlaceholder: 'e.g. nothing spicy, under 30 minutes',
    usage: (remaining: number, limit: number) =>
      remaining === 1
        ? `This is your last request this week (${limit} per week).`
        : `Uses 1 of your ${remaining} remaining requests this week (${limit} per week).`,
    send: 'Get recipes',
    sending: 'Finding recipes…',
    cancel: 'Cancel',
    close: 'Close',
    errorQuota: 'You’ve used this week’s requests.',
    errorNoneFit: 'No new recipes fit this week’s offers. Try different fridge items.',
    errorGeneric: 'Couldn’t get new recipes. Please try again later.',
    needItems: 'Add at least one item from your fridge.',
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
    empty: 'Nothing to buy yet — add recipes to your meal plan first.',
  },

  profile: {
    heading: 'Profile',
    preferences: 'Preferences',
    diet: 'Diet',
    household: 'Household size',
    householdValue: (n: number) => `${n} people`,
    budget: 'Weekly budget',
    allergens: 'Allergens to avoid',
    cuisines: 'Favourite cuisines',
    age: 'Age',
    gender: 'Gender',
    notSet: 'Not set',
    market: 'Home market',
    ingredientsHeading: 'Ingredients',
    dietHint: 'Only recipes that fit are suggested.',
    allergensHint: 'Recipes containing any of these are never suggested.',
    recipesInPlan: 'Recipes in meal plan',
    whiteList: 'Preferred ingredients',
    whiteListHint: 'The planner favours recipes that use these.',
    blackList: 'Ingredients you don’t eat',
    blackListHint: 'Not an allergy — just things you’d rather skip. Allergens go above.',
    noIngredients: 'None yet.',
    ingredientPlaceholder: 'e.g. pumpkin',
    addIngredient: 'Add',
    removeIngredient: (name: string) => `Remove ${name}`,
    save: 'Save preferences',
    saving: 'Saving…',
    saved: 'Saved.',
    saveFailed: 'Couldn’t save. Try again.',
    edit: 'Edit',
    cancel: 'Cancel',
    thisWeek: 'This week',
    basketTotal: 'Basket total',
  },

  weekTime: {
    heading: 'Cooking time per day',
    hint: 'Recipes that take longer than your freest day are never suggested, and each week is checked against these times.',
    unsetHint: 'Not set — the planner assumes you have time every day.',
    perWeek: (total: string) => `${total} a week`,
    noCooking: 'No cooking',
    set: 'Set cooking times',
    clear: 'Clear cooking times',
    day: {
      monday: 'Monday',
      tuesday: 'Tuesday',
      wednesday: 'Wednesday',
      thursday: 'Thursday',
      friday: 'Friday',
      saturday: 'Saturday',
      sunday: 'Sunday',
    },
  },

  diet: {
    normal: 'No restrictions',
    vegetarian: 'Vegetarian',
    vegan: 'Vegan',
    pescetarian: 'Pescetarian',
  },

  allergen: {
    gluten: 'Gluten',
    crustaceans: 'Crustaceans',
    eggs: 'Eggs',
    fish: 'Fish',
    peanuts: 'Peanuts',
    soy: 'Soy',
    milk: 'Milk',
    nuts: 'Tree nuts',
    celery: 'Celery',
    mustard: 'Mustard',
    sesame: 'Sesame',
    sulphites: 'Sulphites',
    lupin: 'Lupin',
    molluscs: 'Molluscs',
  },

  common: {
    loading: 'Loading…',
  },
} as const

export type Strings = typeof en

/** Swap for a German dictionary once one exists. */
export const t = en
