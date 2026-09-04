import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { fetchRecipe } from '../api/client'
import type { Recipe } from '../api/types'
import { DietBadge } from '../components/DietBadge'
import { formatPrice, formatWeekday } from '../format'
import { t } from '../i18n/strings'

/** Offers that don't run the whole week need calling out before you shop. */
const WEEK_START = '2025-11-17'

export function RecipeDetail() {
  const { id } = useParams<{ id: string }>()
  const [recipe, setRecipe] = useState<Recipe | null | undefined>(undefined)

  useEffect(() => {
    let active = true
    fetchRecipe(id ?? '').then((result) => {
      if (active) setRecipe(result ?? null)
    })
    return () => {
      active = false
    }
  }, [id])

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

  const saving = recipe.cost.regularTotalCents - recipe.cost.totalCents

  return (
    <div className="page recipe-detail">
      <Link to="/" className="back-link">
        ← {t.recipe.back}
      </Link>

      <header className="page-head">
        <div>
          <div className="recipe-card-head">
            <DietBadge diet={recipe.dietType} />
            <span className="meta">{t.home.minutes(recipe.minutes)}</span>
            <span className="meta">{t.home.servings(recipe.servings)}</span>
          </div>
          <h1>{recipe.title}</h1>
          <p className="muted">{recipe.summary}</p>
        </div>
        <div className="price-block">
          <span className="price price-large">{formatPrice(recipe.cost.perServingCents)}</span>
          <span className="price-unit">{t.home.perServing}</span>
        </div>
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
                    {ingredient.offer.validFrom > WEEK_START && (
                      <span className="offer-late">
                        {t.recipe.availableFrom(formatWeekday(ingredient.offer.validFrom))}
                      </span>
                    )}
                  </div>
                ) : (
                  <span className="ingredient-pantry">{t.recipe.pantry}</span>
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
                <dt>{t.recipe.recipeTotal}</dt>
                <dd>{formatPrice(recipe.cost.totalCents)}</dd>
              </div>
              <div>
                <dt>{t.recipe.regularPrice}</dt>
                <dd className="struck">{formatPrice(recipe.cost.regularTotalCents)}</dd>
              </div>
              <div>
                <dt>{t.home.totalSaving}</dt>
                <dd className="good">{formatPrice(saving)}</dd>
              </div>
              <div>
                <dt>{t.recipe.leftoverValue}</dt>
                <dd>{formatPrice(recipe.cost.leftoverCents)}</dd>
              </div>
            </dl>
          </section>

          <section className="card">
            <h2>{t.recipe.nutrition}</h2>
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

      <section className="card rationale">
        <h2>{t.recipe.whyThis}</h2>
        <p>{recipe.rationale}</p>
      </section>
    </div>
  )
}
