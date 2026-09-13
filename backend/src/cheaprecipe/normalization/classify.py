"""Classify English ingredients: cookability, diet type, and usage flags.

`use_baking` and `use_drinks` mark the specialised uses; ordinary savoury
cooking is the residual case, flagged by `can_cook` alone.

Output is JSONL rather than a JSON array so a truncated response only costs the
last line instead of the whole batch.
"""

from __future__ import annotations

import json
import logging

import pandas as pd
from openai import OpenAI

from cheaprecipe.llm import DEFAULT_MODEL, complete

log = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 20
# ingredient names and a stray blank line.
TOKENS_PER_RECORD = 60

CLASS_COLUMNS = [
    "ingredient_en",
    "can_cook",
    "diet_type",
    "use_baking",
    "use_drinks",
]

SYSTEM_PROMPT = """
You are helping classify food ingredients for recipes.

For each English ingredient name, decide:

1) can_cook (boolean):
   - true  = can realistically be used in cooking, baking, OR drink recipes
            (examples: meat, seafood, pasta, flour, dairy products, grains, 
            vegetables, wine, beer, cooking oil, stock, cocoa powder, sugar,
            lemon juice, herbs, jam, frozen pizza)
   - false = not typically used as an ingredient in recipes
            (examples: water, cola soft drink, energy drink, coffee,
                cleaning products, non-food items, packaging-only items)

2) diet_type (string):
   - "vegan"       = contains no animal products (no meat, fish, dairy, eggs, honey, gelatin, etc.)
   - "vegetarian"  = may contain dairy, eggs, or honey, but NO meat, fish, or seafood.
   - "normal"      = contains meat, fish, seafood, gelatin, or other non-vegetarian ingredients,
                     OR unclear/mixed (when in doubt, choose "normal").

3) use_baking (boolean):
   - true  = commonly used in baking or desserts (cakes, cookies, breads, pastries, sweets).
   - false = rarely used in baking.

4) use_drinks (boolean):
   - true  = commonly used in drinks (cocktails, smoothies, teas, coffees, punches, etc.).
            Includes many alcohols (wine, rum, vodka, liqueurs) and juices.
   - false = not usually used directly in drink recipes.

A single ingredient can have both flags true, or neither — an ingredient used
only in ordinary savoury cooking has neither, e.g.:
- "onion"    -> use_baking = false, use_drinks = false
- "egg"      -> use_baking = true,  use_drinks = false
- "milk"     -> use_baking = true,  use_drinks = true
- "red wine" -> use_baking = false, use_drinks = true

If you are not sure about a usage category, set it to NULL.
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
    batch_count = (len(ingredients) + batch_size - 1) // batch_size
    
    max_tokens=batch_size * TOKENS_PER_RECORD,   # 1200 at 

    for index, start in enumerate(range(0, len(ingredients), batch_size), start=1):
        batch = ingredients[start : start + batch_size]
        log.debug("classifying batch %d/%d (%d ingredients)", index, batch_count, len(batch))

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
            max_tokens=max_tokens,
            client=client,
        )

        unparsable = 0
        incomplete = 0
        batch_records = 0

        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # Most likely a truncated final line; drop it.
                unparsable += 1
                continue

            if "ingredient_en" not in obj:
                incomplete += 1
                continue

            all_records.append(obj)
            batch_records += 1

        if batch_records < len(batch):
            # Silently dropping lines is how ingredients go missing downstream,
            # so account for every one the batch did not produce.
            log.warning(
                "batch %d/%d: %d/%d ingredients classified "
                "(%d unparsable lines, %d without ingredient_en)",
                index, batch_count, batch_records, len(batch), unparsable, incomplete,
            )

    log.info("classified %d/%d ingredients", len(all_records), len(ingredients))
    return all_records


def add_classification_columns(
    df: pd.DataFrame,
    batch_size: int = DEFAULT_BATCH_SIZE,
    client: OpenAI | None = None,
) -> pd.DataFrame:
    """Classify the distinct ingredients in df and join the flags back on."""
    unique_ingredients = sorted(df["ingredient_en"].dropna().unique().tolist())
    log.info("%d offers -> %d distinct ingredients to classify", len(df), len(unique_ingredients))

    classified = classify_ingredients_batch(
        unique_ingredients, batch_size=batch_size, client=client
    )

    if not classified:
        raise ValueError(
            f"The classifier returned nothing for {len(unique_ingredients)} "
            "ingredients — check the model response format in the logs."
        )

    class_df = pd.DataFrame(classified).drop_duplicates(subset="ingredient_en")
    out = df.merge(class_df, on="ingredient_en", how="left")

    # Rows with no ingredient_en were already reported upstream; what matters
    # here is an ingredient the classifier was given and did not answer for.
    unclassified = out["can_cook"].isna() & out["ingredient_en"].notna()
    if unclassified.any():
        examples = out.loc[unclassified, "ingredient_en"].drop_duplicates().head(5).tolist()
        log.warning(
            "%d/%d offers carry no classification, e.g. %s — selection will skip them",
            int(unclassified.sum()), len(out), examples,
        )

    return out
