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
    mealPlan: 'Meal plan',
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
    working: 'One moment…',
    signupHeading: 'Create your account',
    signupSubheading: 'Plan a week of meals from what’s on offer near you.',
    signupSubmit: 'Create account',
    name: 'Name (optional)',
    username: 'Username',
    noAccount: 'New here?',
    toSignup: 'Create an account',
    haveAccount: 'Already have an account?',
    toSignin: 'Sign in',
    mockNotice:
      'Mock mode (VITE_USE_MOCK): any email and password will sign you in. Nothing leaves your browser.',
    emailRequired: 'Enter an email address to continue.',
    passwordRequired: 'Enter a password to continue.',
    usernameInvalid: 'Choose a username of 3 to 30 characters.',
    passwordTooShort: (n: number) => `Use a password of at least ${n} characters.`,
    wrongCredentials: 'That email and password don’t match an account.',
    taken: 'That username or email already has an account — sign in instead.',
    checkFields: 'Check the email address and try again.',
    unreachable: 'Can’t reach the server. Is the backend running?',
    failed: 'Something went wrong. Please try again.',
  },

  home: {
    heading: 'Recipes for this week',
    subheading: (count: number, from: string, till: string) =>
      `${count} recipes built from offers valid ${from} – ${till}.`,
    planWeek: 'Plan my week',
    planning: 'Planning…',
    planningHint: 'The planner and the critic are working out your week — this takes a minute or two.',
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
    needsMarket: 'Set your home supermarket first — we plan with its offers.',
    setMarket: 'Choose a supermarket',
  },

  planning: {
    heading: 'Planning your week',
    starting: 'Getting started…',
    ready: 'Your week is ready!',
  },

  review: {
    heading: 'Why this week',
    passed: (rounds: number | null) =>
      rounds && rounds > 1
        ? `The critic approved this week after ${rounds} rounds with the planner.`
        : 'The critic approved this week.',
    notPassed: (rounds: number | null) =>
      `The critic still had concerns after ${rounds ?? 'several'} rounds — this is the best week the planner found.`,
    stillOpen: 'Still open',
    tryInstead: 'What could help',
    unreviewed: 'This week was planned before the critic reviewed every plan.',
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

  price: {
    from: (price: string) => `from ${price}`,
    approx: (price: string) => `≈ ${price}`,
    unpricedNote: (n: number) =>
      n === 1 ? '+ 1 item without a price' : `+ ${n} items without a price`,
    estimatedNote: 'incl. regular-price estimates',
  },

  recipe: {
    back: 'Back to recipes',
    ingredients: 'Ingredients',
    method: 'Method',
    onOffer: 'on offer',
    pantry: 'from your pantry',
    regularPrice: (price: string) => `not on offer · ≈ ${price} regular price`,
    noPrice: 'not on offer · no price yet',
    estimatedPart: 'Of which estimated',
    notIncluded: 'Without a price (not included)',
    notIncludedValue: (n: number) => (n === 1 ? '1 item' : `${n} items`),
    estimateHint: 'Items not on offer are priced at a typical regular price.',
    floorHint: 'Some items have no price yet, so the total is a lower bound.',
    costBreakdown: 'Cost',
    perServing: 'Per serving',
    recipeTotal: 'Recipe total',
    leftoverValue: 'Unused leftovers',
    nutrition: 'Nutrition per serving',
    nutritionUnknown: 'Not available for this recipe yet.',
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
    notOnOffer: 'Not on offer',
    otherCategory: 'Other',
    regularPrice: 'regular price',
    noPrice: 'no price yet',
    totalHint: 'Offers at their price; everything else at a typical regular price.',
  },

  meal: {
    breakfast: 'Breakfast',
    lunch: 'Lunch',
    dinner: 'Dinner',
  },

  week: {
    heading: 'Your week',
    subheading: (people: number) =>
      `Monday to Friday, from the recipes in your meal plan — each cooking feeds ${
        people === 1 ? 'you' : `all ${people} of you`
      }, and the rest are leftovers.`,
    empty: 'No recipes in your meal plan yet. Add some from this week’s recipes to fill your week.',
    toRecipes: 'Choose recipes',
    nothing: '—',
    leftovers: 'leftovers',
    emptyMeals: (n: number) => (n === 1 ? '1 meal is still open.' : `${n} meals are still open.`),
    spare: (title: string, n: number) =>
      `${title} makes ${n} more ${n === 1 ? 'portion' : 'portions'} than the week needs.`,
    day: {
      monday: 'Monday',
      tuesday: 'Tuesday',
      wednesday: 'Wednesday',
      thursday: 'Thursday',
      friday: 'Friday',
    } as Record<string, string>,
  },

  profile: {
    heading: 'Profile',
    preferences: 'Preferences',
    diet: 'Diet',
    household: 'Household size',
    householdValue: (n: number) => (n === 1 ? '1 person' : `${n} people`),
    budget: 'Weekly budget',
    allergens: 'Allergens to avoid',
    cuisines: 'Favourite cuisines',
    age: 'Age',
    gender: 'Gender',
    notSet: 'Not set',
    meals: 'Meals to plan',
    mealsHint: 'With breakfast, one of the week’s recipes is a breakfast; the others are for lunch and dinner.',
    markets: 'Home supermarkets',
    marketsHint: 'Your plan uses the offers of these supermarkets. Add every one you shop at.',
    marketsNotSet: 'Not set — needed to plan your week',
    marketSearch: 'Find a supermarket',
    marketPlaceholder: 'Name, street, town or postcode',
    marketSearching: 'Searching…',
    marketNoResults: 'No supermarket found. Try a town or postcode.',
    marketSearchFailed: 'Search is unavailable right now. Try again.',
    marketMinChars: 'Type at least 2 letters.',
    marketAdded: 'Added',
    marketResults: (n: number) => (n === 1 ? '1 supermarket found' : `${n} supermarkets found`),
    removeMarket: (name: string) => `Remove ${name}`,
    marketsRequired: 'Add at least one home supermarket.',
    marketsFull: (max: number) => `That’s the most you can add (${max}). Remove one to choose another.`,
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
    unreachable: 'Can’t reach the server. Is the backend running?',
    loadFailed: 'Couldn’t load this page. Please try again.',
  },
} as const

export type Strings = typeof en

/** Swap for a German dictionary once one exists. */
export const t = en
