"""LLM half of normalization: German product title -> English core ingredient.

Batched because one call per offer is far too slow; batch_size trades latency
against the risk of a truncated response.
"""

from __future__ import annotations

import json
import logging

import pandas as pd
from openai import OpenAI

from cheaprecipe.llm import DEFAULT_MODEL, complete

log = logging.getLogger(__name__)

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
    batch_count = (len(names) + batch_size - 1) // batch_size

    for index, start in enumerate(range(0, len(names), batch_size), start=1):
        batch = names[start : start + batch_size]
        log.debug("translating batch %d/%d (%d names)", index, batch_count, len(batch))

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
                f"Model response for batch {index}/{batch_count} (names {start}-"
                f"{start + len(batch) - 1}) does not contain a JSON array:\n{text}"
            )

        json_str = text[start_idx : end_idx + 1]

        try:
            records = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Failed to parse JSON for batch {index}/{batch_count} "
                f"(names {start}-{start + len(batch) - 1}): {e}\n"
                f"Raw response:\n{text}"
            ) from e

        if len(records) != len(batch):
            # The model dropped or invented entries; the merge below will show
            # up as unmapped titles, so say it here where the batch is known.
            log.warning(
                "batch %d/%d: sent %d names, got %d records back",
                index, batch_count, len(batch), len(records),
            )

        all_records.extend(records)

    log.info("translated %d names into %d records", len(names), len(all_records))
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
    log.info("%d offers -> %d distinct titles to translate", len(df), len(titles))

    records = extract_ingredients_batch(titles, batch_size=batch_size, client=client)

    if not records:
        raise ValueError(
            f"The translator returned nothing for {len(titles)} titles — "
            "check the model response format in the logs."
        )

    df_map = pd.DataFrame(records).drop_duplicates(subset="original")
    out = df.merge(
        df_map,
        left_on=col_name,
        right_on="original",
        how="left",
    ).drop(columns=["original"])

    unmapped = out["ingredient_en"].isna()
    if unmapped.any():
        # Titles the model never returned (or returned under a different
        # spelling) — they survive the merge but carry no ingredient.
        examples = out.loc[unmapped, col_name].drop_duplicates().head(5).tolist()
        log.warning(
            "%d/%d offers have no ingredient_en, e.g. %s",
            int(unmapped.sum()), len(out), examples,
        )

    return out
