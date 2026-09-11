"""SQLAlchemy models: offers, canonical items, recipes, users, generations.

Two halves that meet at `CanonicalIngredient`:

- the ingestion side (`Supermarket` -> `Address` -> `Offer`) stores what the
  scraper found, one row per offer per store per validity window;
- the recipe side (`Recipe` -> `RecipeIngredient`) stores what retrieval and
  the agents produced.

`NormalizationCache` sits between them so a German product title is sent to the
LLM once, not once per weekly run.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --- association tables -----------------------------------------------------

recipe_appliance = Table(
    "recipe_appliance",
    Base.metadata,
    Column("recipe_id", ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "appliance_id",
        ForeignKey("cooking_appliance.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

generation_recipe = Table(
    "generation_recipe",
    Base.metadata,
    Column(
        "generation_id", ForeignKey("generation.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("recipe_id", ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True),
)


# --- users and stores -------------------------------------------------------

class User(Base):
    __tablename__ = "user_account"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    fullname: Mapped[str | None] = mapped_column(String(120))

    age: Mapped[int | None]
    gender: Mapped[str | None] = mapped_column(String(30))

    # Preferences the selection and calculation stages read. Lists rather than
    # comma-joined strings so nothing has to parse them back out.
    diet_type: Mapped[str | None] = mapped_column(String(20))
    cuisines: Mapped[list | None] = mapped_column(JSON)
    allergens: Mapped[list | None] = mapped_column(JSON)
    black_list: Mapped[list | None] = mapped_column(JSON)
    white_list: Mapped[list | None] = mapped_column(JSON)
    health_goal: Mapped[str | None] = mapped_column(String(120))

    fav_supermarket_id: Mapped[int | None] = mapped_column(
        ForeignKey("supermarket.id")
    )
    fav_supermarket: Mapped["Supermarket | None"] = relationship(
        back_populates="users"
    )

    generations: Mapped[list["Generation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"User(id={self.id!r}, username={self.username!r}, "
            f"fullname={self.fullname!r}, "
            f"fav_supermarket_id={self.fav_supermarket_id!r})"
        )


class Supermarket(Base):
    """A chain (EDEKA, REWE), not a branch — branches are `Address` rows."""

    __tablename__ = "supermarket"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)

    addresses: Mapped[list["Address"]] = relationship(
        back_populates="supermarket", cascade="all, delete-orphan"
    )
    users: Mapped[list["User"]] = relationship(back_populates="fav_supermarket")

    def __repr__(self) -> str:
        return f"Supermarket(id={self.id!r}, name={self.name!r})"


class Address(Base):
    """One branch of a chain — the unit offers are actually scoped to."""

    __tablename__ = "address"

    id: Mapped[int] = mapped_column(primary_key=True)
    supermarket_id: Mapped[int] = mapped_column(ForeignKey("supermarket.id"))

    # The id ingestion/edeka.py queries with (DEFAULT_MARKET_ID); without it
    # nothing links a scraped offer back to the store it came from.
    market_id: Mapped[str] = mapped_column(String(50), unique=True)

    street: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    city: Mapped[str | None] = mapped_column(String(80))
    web_url: Mapped[str | None] = mapped_column(String(500))

    supermarket: Mapped["Supermarket"] = relationship(back_populates="addresses")
    offers: Mapped[list["Offer"]] = relationship(
        back_populates="address", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Address(id={self.id!r}, market_id={self.market_id!r}, city={self.city!r})"


# --- ingestion --------------------------------------------------------------

class Offer(Base):
    """One reduced-price offer, as ingestion + normalization produced it.

    Mirrors the columns of new_columns.csv: everything the scraper read, plus
    what the LLM steps added (`ingredient_en` and the classification flags).
    """

    __tablename__ = "offer"
    __table_args__ = (
        # The same product reappears every week; the validity window is what
        # makes a row distinct, so a re-run updates instead of duplicating.
        UniqueConstraint("address_id", "title", "valid_from", name="uq_offer_run"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    address_id: Mapped[int] = mapped_column(ForeignKey("address.id"))

    # As scraped, German.
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(String(255))

    price: Mapped[float]
    price_per_unit: Mapped[float | None]
    quantity_amount: Mapped[float | None]
    quantity_unit: Mapped[str | None] = mapped_column(String(20))

    valid_from: Mapped[date | None]
    valid_till: Mapped[date | None]

    # normalization/ingredients.py
    ingredient_en: Mapped[str | None] = mapped_column(String(120))
    canonical_ingredient_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_ingredient.id")
    )

    # normalization/classify.py — nullable because a batch can come back short,
    # and selection has to be able to tell "not usable" from "never classified".
    can_cook: Mapped[bool | None] = mapped_column(Boolean)
    diet_type: Mapped[str | None] = mapped_column(String(20))
    use_cooking: Mapped[bool | None] = mapped_column(Boolean)
    use_baking: Mapped[bool | None] = mapped_column(Boolean)
    use_drinks: Mapped[bool | None] = mapped_column(Boolean)

    scraped_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    address: Mapped["Address"] = relationship(back_populates="offers")
    canonical_ingredient: Mapped["CanonicalIngredient | None"] = relationship(
        back_populates="offers"
    )
    generation_items: Mapped[list["GenerationItem"]] = relationship(
        back_populates="offer"
    )

    def __repr__(self) -> str:
        return (
            f"Offer(id={self.id!r}, title={self.title!r}, price={self.price!r}, "
            f"ingredient_en={self.ingredient_en!r})"
        )


class NormalizationCache(Base):
    """raw German title -> canonical result, so the LLM is paid for once.

    Backs normalization/cache.py. `model` is recorded because a cached answer
    from a weaker model is worth re-deriving when the default model changes.
    """

    __tablename__ = "normalization_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    ingredient_en: Mapped[str | None] = mapped_column(String(120))
    can_cook: Mapped[bool | None] = mapped_column(Boolean)
    diet_type: Mapped[str | None] = mapped_column(String(20))
    use_cooking: Mapped[bool | None] = mapped_column(Boolean)
    use_baking: Mapped[bool | None] = mapped_column(Boolean)
    use_drinks: Mapped[bool | None] = mapped_column(Boolean)

    model: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"NormalizationCache(raw_name={self.raw_name!r}, "
            f"ingredient_en={self.ingredient_en!r})"
        )


class CanonicalIngredient(Base):
    """The ingredient vocabulary offers and recipes are both resolved against."""

    __tablename__ = "canonical_ingredient"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    food_type: Mapped[str | None] = mapped_column(String(50))

    # A serving size is meaningless without its unit.
    serving_size: Mapped[float | None]
    serving_unit: Mapped[str | None] = mapped_column(String(20))

    # Per 100 g/ml, which is how nutrition tables publish it.
    kcal_per_100: Mapped[float | None]
    protein_per_100: Mapped[float | None]
    carbs_per_100: Mapped[float | None]
    fat_per_100: Mapped[float | None]

    allergens: Mapped[list | None] = mapped_column(JSON)

    offers: Mapped[list["Offer"]] = relationship(back_populates="canonical_ingredient")
    recipe_ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="canonical_ingredient"
    )

    def __repr__(self) -> str:
        return f"CanonicalIngredient(id={self.id!r}, name={self.name!r})"


# --- recipes ----------------------------------------------------------------

class Cuisine(Base):
    __tablename__ = "cuisine"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str | None] = mapped_column(String(450))

    recipes: Mapped[list["Recipe"]] = relationship(back_populates="cuisine")

    def __repr__(self) -> str:
        return f"Cuisine(id={self.id!r}, name={self.name!r})"


class CookingAppliance(Base):
    __tablename__ = "cooking_appliance"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str | None] = mapped_column(String(250))

    recipes: Mapped[list["Recipe"]] = relationship(
        secondary=recipe_appliance, back_populates="appliances"
    )

    def __repr__(self) -> str:
        return f"CookingAppliance(id={self.id!r}, name={self.name!r})"


class Recipe(Base):
    __tablename__ = "recipe"
    __table_args__ = (
        # Spoonacular returns the same recipe across runs; this is what makes
        # retrieval idempotent.
        UniqueConstraint("source", "external_id", name="uq_recipe_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    source: Mapped[str] = mapped_column(String(30), default="spoonacular")
    external_id: Mapped[str | None] = mapped_column(String(50))

    name: Mapped[str] = mapped_column(String(255))
    level: Mapped[str | None] = mapped_column(String(20))
    image_url: Mapped[str | None] = mapped_column(String(500))

    cuisine_id: Mapped[int | None] = mapped_column(ForeignKey("cuisine.id"))

    servings: Mapped[int | None]
    total_time: Mapped[int | None]
    cooking_time: Mapped[int | None]
    waiting_time: Mapped[int | None]
    total_kcal: Mapped[int | None]

    instructions: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    cuisine: Mapped["Cuisine | None"] = relationship(back_populates="recipes")
    appliances: Mapped[list["CookingAppliance"]] = relationship(
        secondary=recipe_appliance, back_populates="recipes"
    )
    ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )
    generations: Mapped[list["Generation"]] = relationship(
        secondary=generation_recipe, back_populates="recipes"
    )

    def __repr__(self) -> str:
        return f"Recipe(id={self.id!r}, name={self.name!r}, source={self.source!r})"


class RecipeIngredient(Base):
    """One line of a recipe: how much of what.

    `name` keeps the recipe's own wording; `canonical_ingredient_id` is the
    resolved match, left null when matching fails so the failure stays visible.
    """

    __tablename__ = "recipe_ingredient"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"))
    canonical_ingredient_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_ingredient.id")
    )

    name: Mapped[str] = mapped_column(String(120))
    amount: Mapped[float | None]
    unit: Mapped[str | None] = mapped_column(String(20))
    optional: Mapped[bool] = mapped_column(Boolean, default=False)

    recipe: Mapped["Recipe"] = relationship(back_populates="ingredients")
    canonical_ingredient: Mapped["CanonicalIngredient | None"] = relationship(
        back_populates="recipe_ingredients"
    )

    def __repr__(self) -> str:
        return (
            f"RecipeIngredient(recipe_id={self.recipe_id!r}, name={self.name!r}, "
            f"amount={self.amount!r}, unit={self.unit!r})"
        )


# --- agent output -----------------------------------------------------------

class Generation(Base):
    """One planner run: the Plan it produced and the Critique it scored.

    Persisting this is what lets you compare models and show a user the plan
    they got last week (see agents/contracts.py).
    """

    __tablename__ = "generation"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE")
    )

    # The inputs, so a run can be reproduced or explained.
    diet_type: Mapped[str | None] = mapped_column(String(20))
    use: Mapped[str | None] = mapped_column(String(20))
    model: Mapped[str | None] = mapped_column(String(80))

    # Critique, flattened — see agents/contracts.py.
    passed: Mapped[bool | None] = mapped_column(Boolean)
    waste_grams: Mapped[float | None]
    total_cost: Mapped[float | None]
    nutrition_ok: Mapped[bool | None] = mapped_column(Boolean)
    issues: Mapped[list | None] = mapped_column(JSON)
    suggestions: Mapped[list | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User | None"] = relationship(back_populates="generations")
    recipes: Mapped[list["Recipe"]] = relationship(
        secondary=generation_recipe, back_populates="generations"
    )
    items: Mapped[list["GenerationItem"]] = relationship(
        back_populates="generation", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"Generation(id={self.id!r}, user_id={self.user_id!r}, "
            f"passed={self.passed!r}, total_cost={self.total_cost!r})"
        )


class GenerationItem(Base):
    """One line of a generation's grocery list: which offer, and how much.

    Deliberately thin. Everything descriptive — name, price, price per unit,
    when the sale starts — lives on the `Offer` row this points at, and offer
    rows are already week-scoped (see the uq_offer_run constraint), so the
    price a plan quoted stays readable forever without copying it here.

    What this table adds is the part the offer cannot know: the amount *this
    plan* needs, and the fact that the plan wanted something at all. `offer_id`
    is null for a line no current offer covers (pantry staples, or an
    ingredient the planner invented) — the null is the signal cost calculation
    needs to flag an unpriceable line.
    """

    __tablename__ = "generation_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    generation_id: Mapped[int] = mapped_column(
        ForeignKey("generation.id", ondelete="CASCADE")
    )
    offer_id: Mapped[int | None] = mapped_column(ForeignKey("offer.id"))

    # Only for lines with no offer; otherwise read it off the offer.
    name: Mapped[str | None] = mapped_column(String(120))

    amount: Mapped[float | None]
    unit: Mapped[str | None] = mapped_column(String(20))

    generation: Mapped["Generation"] = relationship(back_populates="items")
    offer: Mapped["Offer | None"] = relationship(back_populates="generation_items")

    @property
    def display_name(self) -> str | None:
        """What to show on the list — the offer's ingredient, else `name`."""
        if self.offer is not None:
            return self.offer.ingredient_en or self.offer.title
        return self.name

    @property
    def price(self) -> float | None:
        """Price as quoted, or None when no offer covers this line."""
        return self.offer.price if self.offer is not None else None

    def __repr__(self) -> str:
        return (
            f"GenerationItem(name={self.display_name!r}, amount={self.amount!r}, "
            f"unit={self.unit!r}, offer_id={self.offer_id!r})"
        )
