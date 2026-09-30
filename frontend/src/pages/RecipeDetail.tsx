import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { OFFER_WEEK_START, fetchRecipe } from '../api/client'
import type { Recipe } from '../api/types'
import { DietBadge } from '../components/DietBadge'
import { LoadError, loadErrorText } from '../components/LoadError'
import { formatCost, formatPrice, formatWeekday, startsLate } from '../format'
import { t } from '../i18n/strings'


function ClockIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 7.5V12l3 2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

function ServingsIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <circle cx="9" cy="8.5" r="3" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="16.5" cy="9.5" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M3.5 19c.6-3 2.8-4.8 5.5-4.8s4.9 1.8 5.5 4.8M14.5 14.6c2.6-.4 4.9 1.1 5.6 4.4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function RecipeDetail() {
  const { id } = useParams<{ id: string }>()
  const [loadError, setLoadError] = useState<string | null>(null)
  const [recipe, setRecipe] = useState<Recipe | null | undefined>(undefined)

  useEffect(() => {
    let active = true
    fetchRecipe(id ?? '')
      .then((result) => {
        if (active) setRecipe(result ?? null)
      })
      .catch((error) => active && setLoadError(loadErrorText(error)))
    return () => {
      active = false
    }
  }, [id])

  if (loadError) {
    return <LoadError message={loadError} />
  }

  if (recipe === undefined) {
    return <p className="muted">{t.common.loading}</p>
  }

  if (recipe === null) {
    return (
      <div className="page">
        <p className="muted">{t.recipe.notFound}</p>
        <Link to="/">{t.recipe.back}</Link>
      </div>
    )
  }

  return (
    <div className="page recipe-detail">
      <Link to="/" className="back-link">
        ← {t.recipe.back}
      </Link>

      <header className="recipe-head">
        <h1>{recipe.title}</h1>
        <ul className="recipe-facts">
          <li>
            <ClockIcon />
            {t.home.minutes(recipe.minutes)}
          </li>
          <li>
            <ServingsIcon />
            {t.home.servings(recipe.servings)}
          </li>
          <li>
            <DietBadge diet={recipe.dietType} />
          </li>
        </ul>
        {recipe.summary && <p className="muted">{recipe.summary}</p>}
      </header>

      <div className="detail-columns">
        <section className="card">
          <h2>{t.recipe.ingredients}</h2>
          <ul className="ingredient-list">
            {recipe.ingredients.map((ingredient) => (
              <li key={ingredient.name} className="ingredient">
                <div className="ingredient-main">
                  <span className="ingredient-name">{ingredient.name}</span>
                  <span className="ingredient-amount">{ingredient.amount}</span>
                </div>
                {ingredient.offer ? (
                  <div className="ingredient-offer">
                    <span className="offer-title">{ingredient.offer.title}</span>
                    <span className="offer-price">
                      {formatPrice(ingredient.offer.priceCents)} {t.recipe.onOffer}
                    </span>
                    {/* Offers that don't run the whole week need calling out before you shop. */}
                    {startsLate(ingredient.offer.validFrom, OFFER_WEEK_START) && (
                      <span className="offer-late">
                        {t.recipe.availableFrom(formatWeekday(ingredient.offer.validFrom!))}
                      </span>
                    )}
                  </div>
                ) : ingredient.pantry ? (
                  <span className="ingredient-pantry">{t.recipe.pantry}</span>
                ) : (
                  <span className="ingredient-regular">
                    {ingredient.regularPriceCents != null
                      ? t.recipe.regularPrice(formatPrice(ingredient.regularPriceCents))
                      : t.recipe.noPrice}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>

        <div className="detail-side">
          <section className="card">
            <h2>{t.recipe.costBreakdown}</h2>
            <dl className="figure-list">
              <div>
                <dt>{t.recipe.perServing}</dt>
                <dd>
                  {formatCost(
                    recipe.cost.perServingCents,
                    recipe.cost.unpricedCount,
                    recipe.cost.estimatedCents,
                  )}
                </dd>
              </div>
              <div>
                <dt>{t.recipe.recipeTotal}</dt>
                <dd>
                  {formatCost(
                    recipe.cost.totalCents,
                    recipe.cost.unpricedCount,
                    recipe.cost.estimatedCents,
                  )}
                </dd>
              </div>
              {recipe.cost.estimatedCents > 0 && (
                <div>
                  <dt>{t.recipe.estimatedPart}</dt>
                  <dd>{t.price.approx(formatPrice(recipe.cost.estimatedCents))}</dd>
                </div>
              )}
              {recipe.cost.unpricedCount > 0 && (
                <div>
                  <dt>{t.recipe.notIncluded}</dt>
                  <dd>{t.recipe.notIncludedValue(recipe.cost.unpricedCount)}</dd>
                </div>
              )}
              <div>
                <dt>{t.recipe.leftoverValue}</dt>
                <dd>{formatPrice(recipe.cost.leftoverCents)}</dd>
              </div>
            </dl>
            {recipe.cost.unpricedCount > 0 ? (
              <p className="meta">{t.recipe.floorHint}</p>
            ) : (
              recipe.cost.estimatedCents > 0 && <p className="meta">{t.recipe.estimateHint}</p>
            )}
          </section>

          <section className="card">
            <h2>{t.recipe.nutrition}</h2>
            {/* All zeros means no nutrition data for the ingredients yet, not an empty plate. */}
            {Object.values(recipe.nutrition).every((value) => value === 0) ? (
              <p className="muted">{t.recipe.nutritionUnknown}</p>
            ) : (
              <dl className="figure-list">
                <div>
                  <dt>{t.recipe.kcal}</dt>
                  <dd>{recipe.nutrition.kcal} kcal</dd>
                </div>
                <div>
                  <dt>{t.recipe.protein}</dt>
                  <dd>{recipe.nutrition.proteinG} g</dd>
                </div>
                <div>
                  <dt>{t.recipe.carbs}</dt>
                  <dd>{recipe.nutrition.carbsG} g</dd>
                </div>
                <div>
                  <dt>{t.recipe.fat}</dt>
                  <dd>{recipe.nutrition.fatG} g</dd>
                </div>
              </dl>
            )}
            <p className="allergens">
              {recipe.allergens.length > 0
                ? `${t.recipe.allergens}: ${recipe.allergens.join(', ')}`
                : t.recipe.allergenFree}
            </p>
          </section>
        </div>
      </div>

      <section className="card">
        <h2>{t.recipe.method}</h2>
        <ol className="step-list">
          {recipe.steps.map((step, index) => (
            <li key={index}>{step}</li>
          ))}
        </ol>
      </section>
    </div>
  )
}
