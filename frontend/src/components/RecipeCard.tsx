import { Link } from 'react-router-dom'

import { formatPrice } from '../format'
import { t } from '../i18n/strings'
import type { Recipe } from '../api/types'
import { DietBadge } from './DietBadge'

/** The offers this recipe is built on, for the card's ingredient line. */
function offerNames(recipe: Recipe): string[] {
  return recipe.ingredients
    .filter((ingredient) => ingredient.offer)
    .map((ingredient) => ingredient.name)
}

export function RecipeCard({ recipe }: { recipe: Recipe }) {
  const saving = recipe.cost.regularTotalCents - recipe.cost.totalCents

  return (
    <article className="card recipe-card">
      <div className="recipe-card-head">
        <DietBadge diet={recipe.dietType} />
        <span className="meta">{t.home.minutes(recipe.minutes)}</span>
        <span className="meta">{t.home.servings(recipe.servings)}</span>
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
        {saving > 0 && <span className="saving">−{formatPrice(saving)}</span>}
      </div>
    </article>
  )
}
