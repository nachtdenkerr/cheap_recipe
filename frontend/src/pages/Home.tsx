import { useEffect, useState } from 'react'

import { fetchRecipes, regenerateRecipes } from '../api/client'
import type { Recipe } from '../api/types'
import { RecipeCard } from '../components/RecipeCard'
import { formatDate, formatPrice } from '../format'
import { t } from '../i18n/strings'

/** The offer window the recipes were planned against. */
function offerWindow(recipes: Recipe[]): { from: string; till: string } | null {
  const offers = recipes.flatMap((recipe) =>
    recipe.ingredients.flatMap((ingredient) => (ingredient.offer ? [ingredient.offer] : [])),
  )
  if (offers.length === 0) return null

  return {
    from: offers.reduce((min, o) => (o.validFrom < min ? o.validFrom : min), offers[0].validFrom),
    till: offers.reduce((max, o) => (o.validTill > max ? o.validTill : max), offers[0].validTill),
  }
}

export function Home() {
  const [recipes, setRecipes] = useState<Recipe[] | null>(null)
  const [regenerating, setRegenerating] = useState(false)

  useEffect(() => {
    let active = true
    fetchRecipes().then((result) => {
      if (active) setRecipes(result)
    })
    return () => {
      active = false
    }
  }, [])

  async function handleRegenerate() {
    setRegenerating(true)
    setRecipes(await regenerateRecipes())
    setRegenerating(false)
  }

  if (!recipes) {
    return <p className="muted">{t.common.loading}</p>
  }

  const total = recipes.reduce((sum, recipe) => sum + recipe.cost.totalCents, 0)
  const regular = recipes.reduce((sum, recipe) => sum + recipe.cost.regularTotalCents, 0)
  const range = offerWindow(recipes)

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{t.home.heading}</h1>
          {range && (
            <p className="muted">
              {t.home.subheading(recipes.length, formatDate(range.from), formatDate(range.till))}
            </p>
          )}
        </div>
        <button
          type="button"
          className="button-primary"
          onClick={handleRegenerate}
          disabled={regenerating}
        >
          {regenerating ? t.home.regenerating : t.home.regenerate}
        </button>
      </header>

      <section className="stat-row">
        <div className="stat">
          <span className="stat-label">{t.home.totalCost}</span>
          <span className="stat-value">{formatPrice(total)}</span>
        </div>
        <div className="stat">
          <span className="stat-label">{t.home.totalSaving}</span>
          <span className="stat-value stat-value-good">{formatPrice(regular - total)}</span>
        </div>
      </section>

      {recipes.length === 0 ? (
        <p className="muted">{t.home.empty}</p>
      ) : (
        <div className="recipe-grid">
          {recipes.map((recipe) => (
            <RecipeCard key={recipe.id} recipe={recipe} />
          ))}
        </div>
      )}
    </div>
  )
}
