"""LLM half of normalization: German product title -> English core ingredient.

Batched because one call per offer is far too slow; batch_size trades latency
against the risk of a truncated response.
"""

from __future__ import annotations

import json

import pandas as pd
from openai import OpenAI

from cheaprecipe.llm import DEFAULT_MODEL, complete

DEFAULT_BATCH_SIZE = 30

PROMPT_TEMPLATE = """
You are a supermarket product normalizer.

Given a list of German supermarket product names, extract the core ingredient
or product type in English.

Rules:
- Remove brand names (e.g. "Hofglück", "Edeka").
- Ignore quantity, packaging, promotional text ("Aktion", "XXL", etc.).
- Keep each result short and generic (e.g. "pork back roast", "cola soft drink").
- If you are unsure, give your best guess.

Return a JSON array with this exact shape and nothing else:

[
  {{"original": "<original German name>", "ingredient_en": "<english core ingredient>"}},
  ...
]

Here is the list of product names as JSON:

{batch}
"""


def extract_ingredients_batch(
    names: list[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
    model: str = DEFAULT_MODEL,
    client: OpenAI | None = None,
) -> list[dict]:
    """Map German product names to English ingredients.

    names: list of German product names
    returns: [{"original": ..., "ingredient_en": ...}, ...]
    """
    all_records: list[dict] = []

    for start in range(0, len(names), batch_size):
        batch = names[start : start + batch_size]

        prompt = PROMPT_TEMPLATE.format(batch=json.dumps(batch, ensure_ascii=False))

        text = complete(
            [{"role": "user", "content": prompt}],
            model=model,
            max_tokens=1024,
            client=client,
        )

        # Isolate the JSON array in case the model wraps it in prose.
        start_idx = text.find("[")
        end_idx = text.rfind("]")

        if start_idx == -1 or end_idx == -1:
            raise ValueError(
                f"Model response for batch starting at index {start} "
                f"does not contain a JSON array:\n{text}"
            )

        json_str = text[start_idx : end_idx + 1]

        try:
            records = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Failed to parse JSON for batch starting at index {start}: {e}\n"
                f"Raw response:\n{text}"
            ) from e

        all_records.extend(records)

    return all_records


def add_ingredient_column(
    df: pd.DataFrame,
    col_name: str = "title",
    batch_size: int = DEFAULT_BATCH_SIZE,
    client: OpenAI | None = None,
) -> pd.DataFrame:
    """Return df with an `ingredient_en` column joined on `col_name`.

    Only distinct titles are sent to the model — duplicate offers cost nothing.
    """
    titles = df[col_name].dropna().unique().tolist()

    records = extract_ingredients_batch(titles, batch_size=batch_size, client=client)

    df_map = pd.DataFrame(records)  # columns: original, ingredient_en
    return df.merge(
        df_map,
        left_on=col_name,
        right_on="original",
        how="left",
    ).drop(columns=["original"])
