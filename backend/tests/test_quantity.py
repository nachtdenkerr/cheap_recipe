"""Deterministic tests for quantity extraction — no LLM, no network.

The cases are real descriptions from data/offers_clean.csv, chosen for the
rules they exercise rather than for coverage of any particular product.
"""

from pathlib import Path

import pandas as pd
import pytest

from cheaprecipe.normalization import normalize, quantity


def parse(description, price=None):
    return quantity.parse_description(description, price)


def test_plain_pack_size_with_printed_base_price():
    out = parse("Rinderhackfleisch-Patty, mit Salz und Pfeffer gewürzt, 150 g, (1 kg = 19,93)", 2.99)
    assert (out["quantity_amount"], out["quantity_unit"]) == (150.0, "g")
    assert out["quantity_basis"] == quantity.BASIS_PACKAGE
    # The printed base price wins over our own arithmetic.
    assert out["price_per_unit"] == 19.93
    assert out["price_per_unit_unit"] == "kg"


def test_counter_goods_price_is_per_stated_amount():
    """No printed base price + a round base unit = price *per* that amount."""
    out = parse("ohne Haut, Fanggebiet Nordostatlantik, 100 g", 3.49)
    assert out["quantity_basis"] == quantity.BASIS_PRICE
    assert out["price_per_unit"] == 34.90  # not 3.49/kg


def test_multipack_totals_and_deposit_is_separate():
    out = parse("20 x 0,5 L, zzgl. 4,50 Pfand, (1 L = 1,50)", 15.00)
    assert out["quantity_amount"] == 10.0  # 20 x 0,5
    assert out["pack_count"] == 20
    assert out["deposit"] == 4.50  # additional to the price, never part of it
    assert out["price_per_unit"] == 1.50


def test_range_takes_the_conservative_end():
    out = parse("versch. Sorten, 400-420 g, (1 kg = 11,23–10,69)", 4.49)
    assert out["quantity_amount"] == 400.0
    assert out["price_per_unit"] == 11.23


def test_range_with_a_different_unit_on_each_end():
    out = parse("und weitere Sorten, ganze Bohnen, 750 g–1 kg, (1 kg = 17,32–12,99)", 12.99)
    assert (out["quantity_amount"], out["quantity_unit"]) == (750.0, "g")


def test_alcohol_strength_is_not_a_quantity():
    out = parse("versch. Sorten, 14,5% Vol., 0,75 L, (1 L = 10,65)", 7.99)
    assert (out["quantity_amount"], out["quantity_unit"]) == (0.75, "l")


def test_single_purchase_price_is_not_the_quantity():
    """`5,00 €, 3 Stück` is three for five euros, not five euros each."""
    out = parse("mit Haselnussfüllung, Preis bei Einzelkauf: 2,40 €, 3 Stück", 5.00)
    assert (out["quantity_amount"], out["quantity_unit"]) == (3.0, "Stück")
    assert out["price_per_unit"] == pytest.approx(1.6667, abs=1e-4)


def test_bare_stueck_means_one():
    out = parse("Weizenmischbrot mit versch. Belag, Stück", 2.49)
    assert (out["quantity_amount"], out["quantity_unit"]) == (1.0, "Stück")
    assert out["price_per_unit"] == 2.49


def test_pack_size_and_base_unit_together_prices_the_base_unit():
    out = parse("vom Schwein, gewürzt, ca. 320 g, 1 kg", 9.99)
    assert (out["quantity_amount"], out["quantity_unit"]) == (1.0, "kg")
    assert out["price_per_unit"] == 9.99


def test_two_variants_joined_by_oder_take_the_first():
    out = parse("24 x 0,33 L, zzgl. 3,42 Pfand oder 20 x 0,5 L, zzgl. 3,10 Pfand", 13.99)
    assert out["pack_count"] == 24
    assert out["deposit"] == pytest.approx(6.52)  # both clauses are collected


def test_missing_description_is_not_an_error():
    for value in (None, "", float("nan")):
        assert parse(value)["quantity_amount"] is None


def test_drop_unpriced_removes_discount_promotions():
    df = pd.DataFrame({"title": ["Goldbären", "Salami"], "price": [0.0, 2.29]})
    assert normalize.drop_unpriced(df)["title"].tolist() == ["Salami"]


OFFERS_CSV = Path(__file__).resolve().parents[1] / "data" / "offers_clean.csv"


@pytest.mark.skipif(not OFFERS_CSV.exists(), reason="no scraped offers checked in")
def test_derived_base_price_matches_edeka_on_the_real_data():
    """EDEKA prints the base price on packaged goods — use it as an oracle.

    Every row where we can derive it independently must agree, because a
    disagreement means the quantity was misread.
    """
    df = normalize.drop_unpriced(pd.read_csv(OFFERS_CSV)).reset_index(drop=True)

    mismatches = []
    for description, price in zip(df["descriptions"], df["price"]):
        out = quantity.parse_description(description, price)
        printed = out["printed_price_per_unit"]
        derived = out["_derived_price_per_unit"]
        if printed is None or derived is None:
            continue
        low = out["_printed_price_per_unit_low"]
        targets = [printed] + ([low] if low is not None else [])
        if all(abs(derived - t) / t > quantity.TOLERANCE for t in targets):
            mismatches.append((description, derived, printed))

    assert not mismatches, f"{len(mismatches)} rows disagree, e.g. {mismatches[:2]}"


def test_unit_letter_at_the_end_of_a_word_is_not_a_unit():
    """"Bug", "cremig" and "mild-nussig" all end in a valid unit letter."""
    out = parse("ohne Knochen, vom dicken Bug oder Gulasch 100 g", 1.79)
    assert (out["quantity_amount"], out["quantity_unit"]) == (100.0, "g")

    out = parse(
        "mind. 45% Fett i. Tr., mild-nussig oder Delacrème, holländ. Schnittk., 100 g",
        2.29,
    )
    assert out["quantity_amount"] == 100.0
