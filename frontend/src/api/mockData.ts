/**
 * Mockup data standing in for the agent loop.
 *
 * The offers are real rows from the week of 17–22 Nov 2025 (see
 * new_columns.csv) — German titles, actual prices, actual validity windows —
 * so the UI is exercised with the messiness it will really get. Recipes,
 * costings and nutrition are hand-written; `calculation/` will produce them.
 */

import type { Offer, Recipe, ShoppingListItem, User } from './types'

const WEEK = { validFrom: '2025-11-17', validTill: '2025-11-22' }
/** Some offers only start later in the week. */
const SATURDAY = { validFrom: '2025-11-22', validTill: '2025-11-22' }
const THURSDAY = { validFrom: '2025-11-20', validTill: '2025-11-22' }

export const offers = {
  pumpkin: {
    title: 'Unsere Heimat – echt & gut Hokkaido Kürbis',
    ingredientEn: 'hokkaido pumpkin',
    category: 'Obst & Gemüse',
    priceCents: 111,
    dietType: 'vegan',
    ...WEEK,
  },
  gnocchi: {
    title: 'Henglein Kartoffel-Gnocchi',
    ingredientEn: 'potato gnocchi',
    category: 'Sonstiges',
    priceCents: 299,
    dietType: 'vegetarian',
    ...WEEK,
  },
  butter: {
    title: 'Weihenstephan Butter',
    ingredientEn: 'butter',
    category: 'Molkerei & Käse',
    priceCents: 179,
    dietType: 'vegetarian',
    ...WEEK,
  },
  granaPadano: {
    title: 'Grana Padano Riserva',
    ingredientEn: 'grana padano cheese',
    category: 'Molkerei & Käse',
    priceCents: 299,
    dietType: 'vegetarian',
    ...THURSDAY,
  },
  chickenThighs: {
    title: 'Frische Hähnchenschenkel',
    ingredientEn: 'fresh chicken thighs',
    category: 'Fleisch & Wurst',
    priceCents: 499,
    dietType: 'normal',
    ...SATURDAY,
  },
  soupVegetables: {
    title: 'Suppengrün',
    ingredientEn: 'soup vegetables',
    category: 'Obst & Gemüse',
    priceCents: 111,
    dietType: 'vegan',
    ...WEEK,
  },
  savoyCabbage: {
    title: 'Unsere Heimat – echt & gut Wirsing',
    ingredientEn: 'savoy cabbage',
    category: 'Obst & Gemüse',
    priceCents: 149,
    dietType: 'vegan',
    ...WEEK,
  },
  carrots: {
    title: 'EDEKA Bio Möhren',
    ingredientEn: 'carrots',
    category: 'Obst & Gemüse',
    priceCents: 129,
    dietType: 'vegan',
    ...WEEK,
  },
  pasta: {
    title: 'De Cecco italienische Teigwaren',
    ingredientEn: 'pasta',
    category: 'Grundnahrung',
    priceCents: 149,
    dietType: 'vegan',
    ...WEEK,
  },
  spinach: {
    title: 'Iglo Spinat',
    ingredientEn: 'spinach',
    category: 'Tiefkühl',
    priceCents: 179,
    dietType: 'vegan',
    ...WEEK,
  },
  tomatoes: {
    title: 'EDEKA Bio Rispentomaten',
    ingredientEn: 'vine tomatoes',
    category: 'Obst & Gemüse',
    priceCents: 149,
    dietType: 'vegan',
    ...WEEK,
  },
  nilePerch: {
    title: 'Viktoriaseebarschfilets',
    ingredientEn: 'Nile perch fillets',
    category: 'Fisch & Meeresfrüchte',
    priceCents: 199,
    dietType: 'normal',
    ...WEEK,
  },
  potatoes: {
    title: 'EDEKA Herzstücke Raclette Kartoffeln',
    ingredientEn: 'raclette potatoes',
    category: 'Obst & Gemüse',
    priceCents: 249,
    dietType: 'vegan',
    ...THURSDAY,
  },
  lambsLettuce: {
    title: 'Unsere Heimat – echt & gut Feldsalat',
    ingredientEn: "lamb's lettuce",
    category: 'Obst & Gemüse',
    priceCents: 249,
    dietType: 'vegan',
    ...SATURDAY,
  },
  vinegar: {
    title: 'Alnatura Bio Apfelessig naturtrüb',
    ingredientEn: 'organic apple cider vinegar',
    category: 'Sonstiges',
    priceCents: 179,
    dietType: 'vegan',
    ...WEEK,
  },
  skyr: {
    title: 'EDEKA Herzstücke High Protein Skyr Natur',
    ingredientEn: 'skyr yogurt',
    category: 'Molkerei & Käse',
    priceCents: 99,
    dietType: 'vegetarian',
    ...WEEK,
  },
  blueberries: {
    title: 'Heidelbeeren',
    ingredientEn: 'blueberries',
    category: 'Obst & Gemüse',
    priceCents: 399,
    dietType: 'vegan',
    ...WEEK,
  },
  muesli: {
    title: 'Kölln Müsli',
    ingredientEn: 'muesli',
    category: 'Grundnahrung',
    priceCents: 299,
    dietType: 'vegan',
    ...WEEK,
  },
  apples: {
    title: 'Elstar Äpfel',
    ingredientEn: 'elstar apples',
    category: 'Obst & Gemüse',
    priceCents: 79,
    dietType: 'vegan',
    ...WEEK,
  },
} satisfies Record<string, Offer>

export const recipes: Recipe[] = [
  {
    id: 'pumpkin-sage-gnocchi',
    title: 'Roast Hokkaido & Sage Gnocchi',
    summary:
      'Pan-crisped gnocchi with roast pumpkin, brown butter and a shower of Grana Padano.',
    servings: 2,
    minutes: 35,
    dietType: 'vegetarian',
    allergens: ['gluten', 'milk'],
    ingredients: [
      { name: 'hokkaido pumpkin', amount: '500 g', offer: offers.pumpkin },
      { name: 'potato gnocchi', amount: '500 g', offer: offers.gnocchi },
      { name: 'butter', amount: '30 g', offer: offers.butter },
      { name: 'grana padano cheese', amount: '40 g', offer: offers.granaPadano },
      { name: 'sage', amount: '8 leaves', pantry: true },
      { name: 'olive oil, salt, pepper', amount: 'to taste', pantry: true },
    ],
    steps: [
      'Heat the oven to 220 °C. Deseed the pumpkin and cut it into 2 cm wedges — no need to peel a Hokkaido.',
      'Toss with olive oil, salt and pepper, then roast for 20 minutes until the edges catch.',
      'Meanwhile melt the butter in a wide pan over medium heat and fry the gnocchi, undisturbed, until one side is golden — about 6 minutes.',
      'Add the sage leaves to the butter and let them crisp, 30 seconds.',
      'Fold the roast pumpkin through the gnocchi, then grate the Grana Padano over the top and serve straight from the pan.',
    ],
    cost: {
      totalCents: 526,
      perServingCents: 263,
      regularTotalCents: 700,
      leftoverCents: 362,
    },
    nutrition: { kcal: 610, proteinG: 18, carbsG: 78, fatG: 24 },
    rationale:
      'Hokkaido at €1.11 is the cheapest vegetable on offer this week, and it needs neither peeling nor a second cooking step.',
  },
  {
    id: 'chicken-savoy-traybake',
    title: 'One-Tray Chicken with Savoy & Root Veg',
    summary:
      'Chicken thighs roasted over soup greens and shredded savoy, so the vegetables cook in the fat.',
    servings: 4,
    minutes: 55,
    dietType: 'normal',
    allergens: ['celery'],
    ingredients: [
      { name: 'fresh chicken thighs', amount: '4 (approx. 800 g)', offer: offers.chickenThighs },
      { name: 'soup vegetables', amount: '1 bunch', offer: offers.soupVegetables },
      { name: 'savoy cabbage', amount: '½ head', offer: offers.savoyCabbage },
      { name: 'carrots', amount: '250 g', offer: offers.carrots },
      { name: 'paprika, salt, oil', amount: 'to taste', pantry: true },
    ],
    steps: [
      'Heat the oven to 200 °C.',
      'Chop the soup greens and carrots into thumb-sized pieces and spread them over a deep tray. Shred the savoy and pile it on top.',
      'Rub the thighs with oil, salt and paprika and sit them skin-side up on the vegetables.',
      'Roast 45–50 minutes, until the skin is dark and the juices run clear.',
      'Rest 5 minutes, then spoon the pan juices back over the vegetables.',
    ],
    cost: {
      totalCents: 750,
      perServingCents: 188,
      regularTotalCents: 1010,
      leftoverCents: 138,
    },
    nutrition: { kcal: 520, proteinG: 41, carbsG: 18, fatG: 31 },
    rationale:
      'Four portions under €2 each. The soup greens are a €1.11 bundle that would otherwise be bought as three separate vegetables.',
  },
  {
    id: 'spinach-tomato-pasta',
    title: 'Garlicky Spinach & Tomato Pasta',
    summary:
      'A fifteen-minute weeknight plate: frozen spinach wilted into blistered vine tomatoes.',
    servings: 3,
    minutes: 20,
    dietType: 'vegan',
    allergens: ['gluten'],
    ingredients: [
      { name: 'pasta', amount: '500 g', offer: offers.pasta },
      { name: 'spinach', amount: '450 g, frozen', offer: offers.spinach },
      { name: 'vine tomatoes', amount: '400 g', offer: offers.tomatoes },
      { name: 'garlic', amount: '3 cloves', pantry: true },
      { name: 'olive oil, chilli flakes, salt', amount: 'to taste', pantry: true },
    ],
    steps: [
      'Boil the pasta in well-salted water.',
      'While it cooks, halve the tomatoes and blister them cut-side down in a hot, oiled pan without moving them.',
      'Add the sliced garlic and chilli, then the frozen spinach. Cover and let it thaw into the tomatoes, 5 minutes.',
      'Drain the pasta, keeping a cup of the water. Toss everything together, loosening with the pasta water until it clings.',
    ],
    cost: {
      totalCents: 477,
      perServingCents: 159,
      regularTotalCents: 620,
      leftoverCents: 0,
    },
    nutrition: { kcal: 480, proteinG: 17, carbsG: 84, fatG: 8 },
    rationale:
      'Uses every pack completely — no leftovers to waste — and all three items are on offer for the full week.',
  },
  {
    id: 'perch-lambs-lettuce',
    title: 'Pan-Fried Perch, Potatoes & Lamb’s Lettuce',
    summary:
      'Crisp-skinned fillets with buttered potatoes and a sharp apple-cider dressing.',
    servings: 2,
    minutes: 40,
    dietType: 'normal',
    allergens: ['fish', 'milk'],
    ingredients: [
      { name: 'Nile perch fillets', amount: '2 fillets', offer: offers.nilePerch },
      { name: 'raclette potatoes', amount: '600 g', offer: offers.potatoes },
      { name: "lamb's lettuce", amount: '150 g', offer: offers.lambsLettuce },
      { name: 'butter', amount: '20 g', offer: offers.butter },
      { name: 'organic apple cider vinegar', amount: '2 tbsp', offer: offers.vinegar },
      { name: 'oil, salt, pepper', amount: 'to taste', pantry: true },
    ],
    steps: [
      'Boil the potatoes whole in salted water, 20–25 minutes, then halve them and toss with the butter.',
      'Pat the fillets very dry and season. Fry skin-side down in hot oil, pressing flat for the first 30 seconds, 3–4 minutes until the skin releases.',
      'Flip and cook 1 minute more, then rest off the heat.',
      'Whisk the vinegar with oil, salt and pepper and dress the lamb’s lettuce at the last moment.',
      'Plate the potatoes, the fish on top, the salad alongside.',
    ],
    cost: {
      totalCents: 620,
      perServingCents: 310,
      regularTotalCents: 830,
      leftoverCents: 435,
    },
    nutrition: { kcal: 540, proteinG: 38, carbsG: 42, fatG: 22 },
    rationale:
      'The perch is €1.99 for two fillets. Note the lamb’s lettuce and potatoes are Saturday-and-Thursday offers — shop late in the week for this one.',
  },
  {
    id: 'blueberry-skyr-bowl',
    title: 'Blueberry Skyr Breakfast Bowl',
    summary:
      'High-protein skyr under blueberries, grated apple and toasted muesli. Five minutes, no cooking.',
    servings: 2,
    minutes: 5,
    dietType: 'vegetarian',
    allergens: ['milk', 'gluten'],
    ingredients: [
      { name: 'skyr yogurt', amount: '450 g', offer: offers.skyr },
      { name: 'blueberries', amount: '125 g', offer: offers.blueberries },
      { name: 'muesli', amount: '100 g', offer: offers.muesli },
      { name: 'elstar apples', amount: '1 apple', offer: offers.apples },
      { name: 'cinnamon, honey', amount: 'to taste', pantry: true },
    ],
    steps: [
      'Toast the muesli dry in a pan for 2 minutes, until it smells nutty.',
      'Coarsely grate the apple — skin on.',
      'Spoon the skyr into two bowls and top with the apple, blueberries and muesli.',
      'Finish with cinnamon and a thread of honey.',
    ],
    cost: {
      totalCents: 399,
      perServingCents: 200,
      regularTotalCents: 540,
      leftoverCents: 477,
    },
    nutrition: { kcal: 340, proteinG: 21, carbsG: 48, fatG: 6 },
    rationale:
      'Skyr at €0.99 carries 21 g of protein per serving — the cheapest protein per euro in this week’s offers.',
  },
]

/**
 * Offer-level view of everything the five recipes need.
 *
 * One line per offer, not per recipe ingredient: `usedBy` is what stops the
 * butter appearing twice.
 */
export const shoppingList: ShoppingListItem[] = [
  { offer: offers.pumpkin, quantity: 1, usedBy: ['Roast Hokkaido & Sage Gnocchi'], checked: false },
  { offer: offers.gnocchi, quantity: 1, usedBy: ['Roast Hokkaido & Sage Gnocchi'], checked: false },
  {
    offer: offers.butter,
    quantity: 1,
    usedBy: ['Roast Hokkaido & Sage Gnocchi', 'Pan-Fried Perch, Potatoes & Lamb’s Lettuce'],
    checked: false,
  },
  {
    offer: offers.granaPadano,
    quantity: 1,
    usedBy: ['Roast Hokkaido & Sage Gnocchi'],
    checked: false,
  },
  {
    offer: offers.chickenThighs,
    quantity: 1,
    usedBy: ['One-Tray Chicken with Savoy & Root Veg'],
    checked: false,
  },
  {
    offer: offers.soupVegetables,
    quantity: 1,
    usedBy: ['One-Tray Chicken with Savoy & Root Veg'],
    checked: false,
  },
  {
    offer: offers.savoyCabbage,
    quantity: 1,
    usedBy: ['One-Tray Chicken with Savoy & Root Veg'],
    checked: false,
  },
  {
    offer: offers.carrots,
    quantity: 1,
    usedBy: ['One-Tray Chicken with Savoy & Root Veg'],
    checked: false,
  },
  { offer: offers.pasta, quantity: 1, usedBy: ['Garlicky Spinach & Tomato Pasta'], checked: false },
  {
    offer: offers.spinach,
    quantity: 1,
    usedBy: ['Garlicky Spinach & Tomato Pasta'],
    checked: false,
  },
  {
    offer: offers.tomatoes,
    quantity: 1,
    usedBy: ['Garlicky Spinach & Tomato Pasta'],
    checked: false,
  },
  {
    offer: offers.nilePerch,
    quantity: 1,
    usedBy: ['Pan-Fried Perch, Potatoes & Lamb’s Lettuce'],
    checked: false,
  },
  {
    offer: offers.potatoes,
    quantity: 1,
    usedBy: ['Pan-Fried Perch, Potatoes & Lamb’s Lettuce'],
    checked: false,
  },
  {
    offer: offers.lambsLettuce,
    quantity: 1,
    usedBy: ['Pan-Fried Perch, Potatoes & Lamb’s Lettuce'],
    checked: false,
  },
  {
    offer: offers.vinegar,
    quantity: 1,
    usedBy: ['Pan-Fried Perch, Potatoes & Lamb’s Lettuce'],
    checked: false,
  },
  { offer: offers.skyr, quantity: 1, usedBy: ['Blueberry Skyr Breakfast Bowl'], checked: false },
  {
    offer: offers.blueberries,
    quantity: 1,
    usedBy: ['Blueberry Skyr Breakfast Bowl'],
    checked: false,
  },
  { offer: offers.muesli, quantity: 1, usedBy: ['Blueberry Skyr Breakfast Bowl'], checked: false },
  { offer: offers.apples, quantity: 1, usedBy: ['Blueberry Skyr Breakfast Bowl'], checked: false },
]

export const user: User = {
  name: 'Nga',
  email: 'nga@arkadia.hn',
  dietType: 'normal',
  householdSize: 2,
  weeklyBudgetCents: 4000,
  allergens: ['nuts'],
  market: 'EDEKA Frank, Erlachstraße 45',
}
