import { useEffect, useRef, useState } from 'react'

import { fetchRecipes, fetchRefineQuota, planWeek, requestRecipes } from '../api/client'
import type { Recipe, RefineQuota, RefineRequest } from '../api/types'
import { RecipeCard } from '../components/RecipeCard'
import { RecipeRequestPanel } from '../components/RecipeRequestPanel'
import { formatDate, formatPrice, formatWeekday } from '../format'
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

function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path
        d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4A2.5 2.5 0 0 1 4 13.5z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function Home() {
  const [recipes, setRecipes] = useState<Recipe[] | null>(null)
  const [quota, setQuota] = useState<RefineQuota | null>(null)
  const [planning, setPlanning] = useState(false)
  const [panelOpen, setPanelOpen] = useState(false)
  // Recipes that arrived with the last request, badged until the next load.
  const [newIds, setNewIds] = useState<Set<string>>(new Set())
  const gridRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let active = true
    Promise.all([fetchRecipes(), fetchRefineQuota()]).then(([recipeResult, quotaResult]) => {
      if (!active) return
      setRecipes(recipeResult)
      setQuota(quotaResult)
    })
    return () => {
      active = false
    }
  }, [])

  async function handlePlanWeek() {
    setPlanning(true)
    try {
      setRecipes(await planWeek())
      setQuota(await fetchRefineQuota())
    } finally {
      setPlanning(false)
    }
  }

  // No focus handling here: closing a modal <dialog> returns focus to the
  // button that opened it, and after a request the effect below moves it on.
  function closePanel() {
    setPanelOpen(false)
  }

  // After a request, land on the first new recipe — the answer to what was asked.
  useEffect(() => {
    if (newIds.size > 0) {
      gridRef.current?.querySelector<HTMLElement>('.recipe-card.is-new .recipe-card-title a')?.focus()
    }
  }, [newIds])

  async function handleRequest(request: RefineRequest) {
    const before = new Set((recipes ?? []).map((recipe) => recipe.id))
    const response = await requestRecipes(request)
    setRecipes(response.recipes)
    setQuota(response.quota)
    setPanelOpen(false)
    setNewIds(new Set(response.recipes.filter((r) => !before.has(r.id)).map((r) => r.id)))
  }

  if (!recipes) {
    return <p className="muted">{t.common.loading}</p>
  }

  const planned = recipes.filter((recipe) => recipe.inMealPlan)
  const total = planned.reduce((sum, recipe) => sum + recipe.cost.totalCents, 0)

  function replace(updated: Recipe) {
    setRecipes((current) => current?.map((r) => (r.id === updated.id ? updated : r)) ?? null)
  }
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
        {quota && !quota.weeklyPlanDone ? (
          <button
            type="button"
            className="button-primary"
            onClick={handlePlanWeek}
            disabled={planning}
          >
            {planning ? t.home.planning : t.home.planWeek}
          </button>
        ) : (
          quota && (
            <div className="ask-block">
              <button
                type="button"
                className="button-primary ask-button"
                onClick={() => setPanelOpen(true)}
                disabled={quota.remaining === 0}
                aria-describedby="ask-quota"
              >
                <ChatIcon />
                {t.home.askForRecipes}
                <span className="ask-badge" id="ask-quota">
                  {t.home.requestsLeft(quota.remaining)}
                </span>
              </button>
              {quota.remaining === 0 && (
                <p className="meta">{t.home.resetsOn(formatWeekday(quota.resetsAt))}</p>
              )}
            </div>
          )
        )}
      </header>

      <section className="stat-row">
        <div className="stat">
          <span className="stat-label">{t.home.plannedCount}</span>
          <span className="stat-value">{planned.length}</span>
        </div>
        <div className="stat">
          <span className="stat-label">{t.home.totalCost}</span>
          <span className="stat-value">{formatPrice(total)}</span>
        </div>
      </section>

      {recipes.length === 0 ? (
        <p className="muted">{t.home.empty}</p>
      ) : (
        <div className="recipe-grid" ref={gridRef}>
          {recipes.map((recipe) => (
            <RecipeCard
              key={recipe.id}
              recipe={recipe}
              isNew={newIds.has(recipe.id)}
              onChange={replace}
            />
          ))}
        </div>
      )}

      {quota && (
        <RecipeRequestPanel
          open={panelOpen}
          onClose={closePanel}
          unplannedCount={recipes.filter((recipe) => !recipe.inMealPlan).length}
          remaining={quota.remaining}
          limit={quota.limit}
          onSubmit={handleRequest}
        />
      )}
    </div>
  )
}
