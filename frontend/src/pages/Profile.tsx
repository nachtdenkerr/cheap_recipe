import { useEffect, useState } from 'react'

import { fetchRecipes, fetchUser } from '../api/client'
import type { Recipe, User } from '../api/types'
import { formatPrice } from '../format'
import { t } from '../i18n/strings'

export function Profile() {
  const [user, setUser] = useState<User | null>(null)
  const [recipes, setRecipes] = useState<Recipe[]>([])

  useEffect(() => {
    let active = true
    Promise.all([fetchUser(), fetchRecipes()]).then(([userResult, recipeResult]) => {
      if (!active) return
      setUser(userResult)
      setRecipes(recipeResult)
    })
    return () => {
      active = false
    }
  }, [])

  if (!user) {
    return <p className="muted">{t.common.loading}</p>
  }

  const total = recipes.reduce((sum, recipe) => sum + recipe.cost.totalCents, 0)
  const regular = recipes.reduce((sum, recipe) => sum + recipe.cost.regularTotalCents, 0)
  const budgetUsed = Math.min(100, Math.round((total / user.weeklyBudgetCents) * 100))

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{t.profile.heading}</h1>
          <p className="muted">
            {user.name} · {user.email}
          </p>
        </div>
      </header>

      <div className="detail-columns">
        <section className="card">
          <h2>{t.profile.preferences}</h2>
          <dl className="figure-list">
            <div>
              <dt>{t.profile.diet}</dt>
              <dd>{t.diet[user.dietType]}</dd>
            </div>
            <div>
              <dt>{t.profile.household}</dt>
              <dd>{t.profile.householdValue(user.householdSize)}</dd>
            </div>
            <div>
              <dt>{t.profile.budget}</dt>
              <dd>{formatPrice(user.weeklyBudgetCents)}</dd>
            </div>
            <div>
              <dt>{t.profile.allergens}</dt>
              <dd>
                {user.allergens.length > 0 ? user.allergens.join(', ') : t.profile.noAllergens}
              </dd>
            </div>
            <div>
              <dt>{t.profile.market}</dt>
              <dd>{user.market}</dd>
            </div>
          </dl>
          <p className="notice">{t.profile.mockNotice}</p>
        </section>

        <div className="detail-side">
          <section className="card">
            <h2>{t.profile.thisWeek}</h2>
            <dl className="figure-list">
              <div>
                <dt>{t.profile.recipesPlanned}</dt>
                <dd>{recipes.length}</dd>
              </div>
              <div>
                <dt>{t.profile.basketTotal}</dt>
                <dd>{formatPrice(total)}</dd>
              </div>
              <div>
                <dt>{t.profile.saved}</dt>
                <dd className="good">{formatPrice(regular - total)}</dd>
              </div>
            </dl>

            <div
              className="budget-bar"
              role="img"
              aria-label={`${formatPrice(total)} of ${formatPrice(user.weeklyBudgetCents)}`}
            >
              <span style={{ width: `${budgetUsed}%` }} />
            </div>
            <p className="muted budget-caption">
              {formatPrice(total)} / {formatPrice(user.weeklyBudgetCents)}
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}
