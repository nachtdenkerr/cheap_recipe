"""Classify English ingredients: cookability, diet type, and usage flags.

Output is JSONL rather than a JSON array so a truncated response only costs the
last line instead of the whole batch.
"""

from __future__ import annotations

import json

import pandas as pd
from openai import OpenAI

from cheaprecipe.llm import DEFAULT_MODEL, complete

DEFAULT_BATCH_SIZE = 20

CLASS_COLUMNS = [
    "ingredient_en",
    "can_cook",
    "diet_type",
    "use_cooking",
    "use_baking",
    "use_drinks",
]

SYSTEM_PROMPT = """
You are helping classify food ingredients for recipes.

For each English ingredient name, decide:

1) can_cook (boolean):
   - true  = can realistically be used in cooking, baking, OR drink recipes
            (examples: pork, rice, carrots, onions, red wine, white wine, beer,
                       stock, cocoa powder, sugar, lemon juice)
   - false = not typically used as an ingredient in recipes
            (examples: cola soft drink, energy drink, cleaning products,
                       non-food items, packaging-only items)

2) diet_type (string):
   - "vegan"       = contains no animal products (no meat, fish, dairy, eggs, honey, gelatin, etc.)
   - "vegetarian"  = may contain dairy, eggs, or honey, but NO meat, fish, or seafood.
   - "normal"      = contains meat, fish, seafood, gelatin, or other non-vegetarian ingredients,
                     OR unclear/mixed (when in doubt, choose "normal").

3) use_cooking (boolean):
   - true  = commonly used in savory / general cooking (stir-fries, stews, sauces, roasts, etc.).
   - false = not normally used in cooking.

4) use_baking (boolean):
   - true  = commonly used in baking or desserts (cakes, cookies, breads, pastries, sweets).
   - false = rarely used in baking.

5) use_drinks (boolean):
   - true  = commonly used in drinks (cocktails, smoothies, teas, coffees, punches, etc.).
            Includes many alcohols (wine, rum, vodka, liqueurs) and juices.
   - false = not usually used directly in drink recipes.

A single ingredient can have multiple true flags, e.g.:
- "egg"      -> use_cooking = true, use_baking = true, use_drinks = false
- "milk"     -> use_cooking = true, use_baking = true, use_drinks = true
- "red wine" -> use_cooking = true, use_baking = maybe true, use_drinks = true

If you are not sure about a usage category, set it to false.
"""

USER_PROMPT_TEMPLATE = """
Classify each of these ingredient names.

OUTPUT FORMAT (IMPORTANT):

- Output ONE valid JSON object PER LINE (JSONL format).
- Do NOT wrap them in an array.
- Do NOT add commas between lines.
- Do NOT add any explanations or extra text.

Each line must be a JSON object with this shape:

{{
  "ingredient_en": "<ingredient name>",
  "can_cook": true or false,
  "diet_type": "vegan" or "vegetarian" or "normal",
  "use_cooking": true or false,
  "use_baking": true or false,
  "use_drinks": true or false
}}

Here is the list of ingredient names as a JSON array:

{batch}
"""


def classify_ingredients_batch(
    ingredients: list[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
    model: str = DEFAULT_MODEL,
    client: OpenAI | None = None,
) -> list[dict]:
    """Classify ingredients with can_cook, diet_type and the three use_* flags.

    ingredients: list of English ingredient names
    returns: list of dicts, one per successfully parsed line
    """
    all_records: list[dict] = []

    for start in range(0, len(ingredients), batch_size):
        batch = ingredients[start : start + batch_size]

        raw_text = complete(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": USER_PROMPT_TEMPLATE.format(
                        batch=json.dumps(batch, ensure_ascii=False)
                    ),
                },
            ],
            model=model,
            max_tokens=800,
            client=client,
        )

        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # Most likely a truncated final line; drop it.
                continue

            if "ingredient_en" not in obj:
                continue

            all_records.append(obj)

    return all_records


def add_classification_columns(
    df: pd.DataFrame,
    batch_size: int = DEFAULT_BATCH_SIZE,
    client: OpenAI | None = None,
) -> pd.DataFrame:
    """Classify the distinct ingredients in df and join the flags back on."""
    unique_ingredients = sorted(df["ingredient_en"].dropna().unique().tolist())

    classified = classify_ingredients_batch(
        unique_ingredients, batch_size=batch_size, client=client
    )

    class_df = pd.DataFrame(classified)
    return df.merge(class_df, on="ingredient_en", how="left")
