"""Extract quantity, unit and price per unit from an offer's description.

Deterministic — no LLM. The field follows a tight grammar:

    <prose, 0..n commas>, [N x] <amount>[-<amount>] <unit>[, zzgl. <X> Pfand][, (1 kg = <Y>)]

so the quantity is the last element once the deposit clause and the base-price
parenthetical are stripped off the end.

The parenthetical is also a free correctness check: where EDEKA prints the base
price we can derive it ourselves and compare. A mismatch means the parse is
wrong, and `add_quantity_columns` logs it rather than writing a bad number.
"""

from __future__ import annotations

import logging
import re

import pandas as pd

log = logging.getLogger(__name__)

# German price labelling: base price is mandatory on packaged goods, so its
# absence marks counter goods sold loose, where the price is quoted *per* the
# stated amount instead of *for* it.
BASIS_PACKAGE = "package"
BASIS_PRICE = "price_basis"

# Quantities that mean "the price refers to this much" when no base price is
# printed. Anything else is read as a pack size.
PRICE_BASIS_QUANTITIES = {
    (100.0, "g"),
    (1.0, "kg"),
    (1.0, "l"),
    (1.0, "stück"),
    (1.0, "bund"),
}

UNITS = r"g|kg|ml|l|L|Stück|Stueck|Bund"

# `(1 kg = 19,93)` or `(1 L = 11,23–10,69)` — the printed base price.
PAREN_RE = re.compile(
    r"\(\s*1\s*(?P<unit>kg|L|l)\s*=\s*(?P<high>[\d.,]+)"
    r"(?:\s*[–-]\s*(?P<low>[\d.,]+))?\s*\)"
)

# `zzgl. 0,25 Pfand` — refundable, additional to the price, never part of it.
DEPOSIT_RE = re.compile(r",?\s*zzgl\.\s*(?P<amount>[\d.,]+)\s*Pfand", re.IGNORECASE)

# A unit must not be the tail of a word: "Bug", "cremig" and "mild-nussig" all
# end in a valid unit letter, and matched as a bare `g` before this guard.
NOT_A_WORD_TAIL = r"(?<![A-Za-zÄÖÜäöüß])"

# `20 x 0,5 L`, `400-420 g`, `100 g`, `Stück`. An amount is required except for
# the countable units, where a bare "Stück" means one.
QUANTITY_RE = re.compile(
    rf"(?:(?P<pack>\d+)\s*x\s*)?"
    rf"(?:(?P<low>\d+(?:[.,]\d+)?)(?:\s*[–-]\s*(?P<high>\d+(?:[.,]\d+)?))?\s*"
    rf"{NOT_A_WORD_TAIL}(?P<unit>{UNITS})"
    rf"|{NOT_A_WORD_TAIL}(?P<bare_unit>Stück|Stueck|Bund))\b"
)

# `750 g–1 kg` — a range whose two ends carry different units.
MIXED_RANGE_RE = re.compile(
    rf"(?P<low>\d+(?:[.,]\d+)?)\s*(?<![A-Za-zÄÖÜäöüß])(?P<low_unit>{UNITS})\s*[–-]\s*"
    rf"(?P<high>\d+(?:[.,]\d+)?)\s*(?<![A-Za-zÄÖÜäöüß])(?P<high_unit>{UNITS})\s*$"
)

TO_BASE = {"g": ("kg", 1000.0), "kg": ("kg", 1.0), "ml": ("l", 1000.0), "l": ("l", 1.0)}

# How closely a derived base price must match the printed one to be believed.
TOLERANCE = 0.02


def _to_float(text: str | None) -> float | None:
    """Parse a German decimal ('1.234,56') into a float."""
    if text is None:
        return None
    try:
        return float(text.replace(".", "").replace(",", ".")) if "," in text else float(text)
    except ValueError:
        return None


def _canonical_unit(unit: str) -> str:
    unit = unit.strip()
    if unit.lower() in ("l", "ml", "g", "kg"):
        return unit.lower()
    return "Stück" if unit.lower() in ("stück", "stueck") else unit


def parse_description(description: str | None, price: float | None = None) -> dict:
    """Pull quantity, unit, deposit and price per unit out of one description.

    Returns a dict with keys: quantity_amount, quantity_unit, quantity_basis,
    pack_count, deposit, price_per_unit, price_per_unit_unit,
    printed_price_per_unit. Values are None where the field is not derivable.
    """
    empty = {
        "quantity_amount": None,
        "quantity_unit": None,
        "quantity_basis": None,
        "pack_count": None,
        "deposit": None,
        "price_per_unit": None,
        "price_per_unit_unit": None,
        "printed_price_per_unit": None,
        "_printed_price_per_unit_low": None,
        "_derived_price_per_unit": None,
    }

    if not isinstance(description, str) or not description.strip():
        return empty

    text = description.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()

    paren = PAREN_RE.search(text)
    text = PAREN_RE.sub("", text)

    deposits = [_to_float(m.group("amount")) for m in DEPOSIT_RE.finditer(text)]
    text = DEPOSIT_RE.sub("", text).strip().rstrip(",").strip()

    # `24 x 0,33 L oder 20 x 0,5 L` offers two variants; the first is the
    # headline one. (`oder` usually just joins product names, which is why this
    # only splits when the left side ends in a quantity.)
    for part in re.split(r"\s+oder\s+", text):
        if re.search(QUANTITY_RE.pattern + r"\s*$", part.strip()):
            text = part.strip()
            break

    # Anchored at the end first — that is where the grammar puts it. Falling
    # back to the first match anywhere catches the rare trailing adjective
    # ("6 x 90 ml, auch Max Pistachio, 4 x 90 ml, tiefgefroren").
    mixed = MIXED_RANGE_RE.search(text)
    match = re.search(QUANTITY_RE.pattern + r"\s*$", text) or QUANTITY_RE.search(text)
    if not match and not mixed:
        return {**empty, "deposit": sum(deposits) if deposits else None}

    if mixed:
        # Conservative end of the range, same convention as a same-unit range.
        unit = _canonical_unit(mixed.group("low_unit"))
        pack = None
        low = _to_float(mixed.group("low"))
    else:
        unit = _canonical_unit(match.group("unit") or match.group("bare_unit"))
        pack = int(match.group("pack")) if match.group("pack") else None
        low = _to_float(match.group("low"))

    # A bare "Stück" means one.
    if low is None:
        low = 1.0

    # For a range, the low end is the conservative read: least product for the
    # money, so the highest price per unit — which is the end EDEKA prints first.
    amount = low * (pack or 1)

    printed_ppu = _to_float(paren.group("high")) if paren else None
    printed_low = _to_float(paren.group("low")) if paren else None
    printed_unit = paren.group("unit").lower() if paren else None

    if paren:
        basis = BASIS_PACKAGE
    elif (low, unit.lower()) in PRICE_BASIS_QUANTITIES and not pack:
        basis = BASIS_PRICE
    else:
        basis = BASIS_PACKAGE

    # price / amount-in-base-units, identical arithmetic for both bases; what
    # differs is what quantity_amount *means* (received vs quoted).
    price_per_unit = None
    price_per_unit_unit = None
    if price:
        if unit.lower() in TO_BASE:
            base_unit, divisor = TO_BASE[unit.lower()]
            in_base = amount / divisor
            if in_base:
                price_per_unit = round(price / in_base, 4)
                price_per_unit_unit = base_unit
        elif unit in ("Stück", "Bund") and amount:
            # Countable goods: the "base price" is simply the price per piece.
            price_per_unit = round(price / amount, 4)
            price_per_unit_unit = unit

    return {
        "quantity_amount": amount,
        "quantity_unit": unit,
        "quantity_basis": basis,
        "pack_count": pack,
        "deposit": sum(deposits) if deposits else None,
        "price_per_unit": printed_ppu if printed_ppu is not None else price_per_unit,
        "price_per_unit_unit": printed_unit or price_per_unit_unit,
        "printed_price_per_unit": printed_ppu,
        "_printed_price_per_unit_low": printed_low,
        "_derived_price_per_unit": price_per_unit,
    }


def add_quantity_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add the parsed quantity columns, and check them against EDEKA's own.

    Where a base price is printed we derive it independently and compare; the
    rows that disagree are the rows whose quantity was misread.
    """
    parsed = [
        parse_description(desc, price)
        for desc, price in zip(df["descriptions"], df["price"])
    ]

    derived = [p.pop("_derived_price_per_unit", None) for p in parsed]
    printed_low = [p.pop("_printed_price_per_unit_low", None) for p in parsed]
    out = pd.concat([df.reset_index(drop=True), pd.DataFrame(parsed)], axis=1)

    missing = out["quantity_amount"].isna()
    if missing.any():
        examples = df.loc[missing.values, "descriptions"].head(3).tolist()
        log.warning(
            "%d/%d descriptions carry no readable quantity, e.g. %s",
            int(missing.sum()), len(out), examples,
        )

    checked = mismatched = 0
    for index, (printed, low, own) in enumerate(
        zip(out["printed_price_per_unit"], printed_low, derived)
    ):
        if pd.isna(printed) or own is None:
            continue
        checked += 1
        # A printed range gives two correct answers, one per end of the size
        # range; matching either one means the quantity was read correctly.
        targets = [printed] + ([low] if low is not None else [])
        if all(abs(own - t) / t > TOLERANCE for t in targets):
            mismatched += 1
            if mismatched <= 3:
                log.warning(
                    "quantity parse disagrees with the printed base price "
                    "(derived %.2f vs printed %.2f): %r",
                    own, printed, out.at[index, "descriptions"],
                )

    parsed_count = int(out["quantity_amount"].notna().sum())
    if checked:
        log.info(
            "quantities parsed for %d/%d offers; %d/%d agreed with the printed base price",
            parsed_count, len(out), checked - mismatched, checked,
        )
    else:
        # Nothing to cross-check against; still say how much was read.
        log.info("quantities parsed for %d/%d offers", parsed_count, len(out))

    return out.drop(columns=["printed_price_per_unit"])
