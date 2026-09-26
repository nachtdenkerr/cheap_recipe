import { useState } from 'react'
import { Link } from 'react-router-dom'

import { setFavourite, setInMealPlan } from '../api/client'
import type { Recipe } from '../api/types'
import { formatPrice } from '../format'
import { t } from '../i18n/strings'
import { DietBadge } from './DietBadge'

/** The offers this recipe is built on, for the card's ingredient line. */
function offerNames(recipe: Recipe): string[] {
  return recipe.ingredients
    .filter((ingredient) => ingredient.offer)
    .map((ingredient) => ingredient.name)
}

function HeartIcon({ filled }: { filled: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path
        d="M12 20.5s-7.5-4.6-7.5-10.1A4.4 4.4 0 0 1 12 7.6a4.4 4.4 0 0 1 7.5 2.8c0 5.5-7.5 10.1-7.5 10.1z"
        fill={filled ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  )
}

interface Props {
  recipe: Recipe
  /** Arrived with the last "ask for new recipes" request. */
  isNew?: boolean
  /** Called with the server's copy after a heart or meal-plan change. */
  onChange: (recipe: Recipe) => void
}

export function RecipeCard({ recipe, isNew = false, onChange }: Props) {
  const [pending, setPending] = useState<'favourite' | 'plan' | null>(null)

  async function run(kind: 'favourite' | 'plan', request: () => Promise<Recipe>) {
    setPending(kind)
    try {
      onChange(await request())
    } finally {
      setPending(null)
    }
  }

  return (
    <article
      className={['card', 'recipe-card', recipe.inMealPlan && 'planned', isNew && 'is-new']
        .filter(Boolean)
        .join(' ')}
    >
      <div className="recipe-card-head">
        <div className="recipe-card-tags">
          {isNew && <span className="badge badge-new">{t.home.newBadge}</span>}
          <DietBadge diet={recipe.dietType} />
          <span className="meta recipe-card-meta">
            {t.home.minutes(recipe.minutes)} · {t.home.servings(recipe.servings)}
          </span>
        </div>
        <button
          type="button"
          className={recipe.isFavourite ? 'heart-button active' : 'heart-button'}
          aria-pressed={recipe.isFavourite}
          aria-label={
            recipe.isFavourite ? t.home.unfavourite(recipe.title) : t.home.favourite(recipe.title)
          }
          disabled={pending === 'favourite'}
          onClick={() => run('favourite', () => setFavourite(recipe.id, !recipe.isFavourite))}
        >
          <HeartIcon filled={recipe.isFavourite} />
        </button>
      </div>

      <h2 className="recipe-card-title">
        <Link to={`/recipes/${recipe.id}`}>{recipe.title}</Link>
      </h2>
      <p className="recipe-card-summary">{recipe.summary}</p>

      <ul className="chip-list">
        {offerNames(recipe).map((name) => (
          <li key={name} className="chip">
            {name}
          </li>
        ))}
      </ul>

      <div className="recipe-card-foot">
        <div>
          <span className="price">{formatPrice(recipe.cost.perServingCents)}</span>
          <span className="price-unit"> {t.home.perServing}</span>
        </div>
        <button
          type="button"
          className={recipe.inMealPlan ? 'button-quiet plan-button' : 'button-primary plan-button'}
          aria-pressed={recipe.inMealPlan}
          title={recipe.inMealPlan ? t.home.removeFromPlan : undefined}
          disabled={pending === 'plan'}
          onClick={() => run('plan', () => setInMealPlan(recipe.id, !recipe.inMealPlan))}
        >
          {recipe.inMealPlan ? `✓ ${t.home.inPlan}` : t.home.addToPlan}
        </button>
      </div>
    </article>
  )
}
