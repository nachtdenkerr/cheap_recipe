import { useEffect, useState } from 'react'

import { fetchRecipes, fetchUser, savePreferences } from '../api/client'
import type { Allergen, DietType, Recipe, User } from '../api/types'
import { ALLERGENS, DIETS } from '../api/vocabulary'
import { IngredientListEditor } from '../components/IngredientListEditor'
import { formatPrice } from '../format'
import { t } from '../i18n/strings'

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

function sameList(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((name, index) => name === b[index])
}

/** Order-insensitive, for checkbox sets. */
function sameSet(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((item) => b.includes(item))
}

function listOrNone(items: string[]): string {
  return items.length > 0 ? items.join(', ') : t.profile.notSet
}

export function Profile() {
  const [user, setUser] = useState<User | null>(null)
  const [recipes, setRecipes] = useState<Recipe[]>([])
  const [dietType, setDietType] = useState<DietType>('normal')
  const [allergens, setAllergens] = useState<Allergen[]>([])
  const [whiteList, setWhiteList] = useState<string[]>([])
  const [blackList, setBlackList] = useState<string[]>([])
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [editing, setEditing] = useState(false)

  function setDraftFrom(saved: User) {
    setDietType(saved.dietType)
    setAllergens(saved.allergens)
    setWhiteList(saved.whiteList)
    setBlackList(saved.blackList)
  }

  useEffect(() => {
    let active = true
    Promise.all([fetchUser(), fetchRecipes()]).then(([userResult, recipeResult]) => {
      if (!active) return
      setUser(userResult)
      setDraftFrom(userResult)
      setRecipes(recipeResult)
    })
    return () => {
      active = false
    }
  }, [])

  if (!user) {
    return <p className="muted">{t.common.loading}</p>
  }

  const dirty =
    dietType !== user.dietType ||
    !sameSet(allergens, user.allergens) ||
    !sameList(whiteList, user.whiteList) ||
    !sameList(blackList, user.blackList)

  function toggleAllergen(allergen: Allergen) {
    setAllergens((list) =>
      list.includes(allergen) ? list.filter((a) => a !== allergen) : [...list, allergen],
    )
    setSaveState('idle')
  }

  // An ingredient can be wanted or unwanted, not both: adding it to one list
  // takes it off the other.
  function addPreferred(name: string) {
    setWhiteList((list) => (list.includes(name) ? list : [...list, name]))
    setBlackList((list) => list.filter((item) => item !== name))
    setSaveState('idle')
  }

  function addDisliked(name: string) {
    setBlackList((list) => (list.includes(name) ? list : [...list, name]))
    setWhiteList((list) => list.filter((item) => item !== name))
    setSaveState('idle')
  }

  function handleEdit() {
    setDraftFrom(user!)
    setSaveState('idle')
    setEditing(true)
  }

  async function handleSave() {
    if (!dirty) {
      setEditing(false)
      return
    }
    setSaveState('saving')
    try {
      const updated = await savePreferences({ dietType, allergens, whiteList, blackList })
      setUser(updated)
      setDraftFrom(updated)
      setSaveState('saved')
      setEditing(false)
    } catch {
      // Stay in edit mode so nothing typed is lost.
      setSaveState('error')
    }
  }

  function handleCancel() {
    setDraftFrom(user!)
    setSaveState('idle')
    setEditing(false)
  }

  const planned = recipes.filter((recipe) => recipe.inMealPlan)
  const total = planned.reduce((sum, recipe) => sum + recipe.cost.totalCents, 0)
  const budget = user.weeklyBudgetCents
  const budgetUsed = budget ? Math.min(100, Math.round((total / budget) * 100)) : 0

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
        <section className="card profile-preferences">
          <div className="card-head">
            <h2>{t.profile.preferences}</h2>
            {!editing && (
              <button type="button" className="button-quiet" onClick={handleEdit}>
                {t.profile.edit}
              </button>
            )}
          </div>

          {editing ? (
            <>
              <fieldset className="choice-group">
                <legend>{t.profile.diet}</legend>
                <p className="meta">{t.profile.dietHint}</p>
                <div className="choice-options">
                  {DIETS.map((diet) => (
                    <label key={diet} className="choice">
                      <input
                        type="radio"
                        name="diet"
                        value={diet}
                        checked={dietType === diet}
                        onChange={() => {
                          setDietType(diet)
                          setSaveState('idle')
                        }}
                      />
                      {t.diet[diet]}
                    </label>
                  ))}
                </div>
              </fieldset>

              <fieldset className="choice-group">
                <legend>{t.profile.allergens}</legend>
                <p className="meta">{t.profile.allergensHint}</p>
                <div className="choice-options">
                  {ALLERGENS.map((allergen) => (
                    <label key={allergen} className="choice">
                      <input
                        type="checkbox"
                        checked={allergens.includes(allergen)}
                        onChange={() => toggleAllergen(allergen)}
                      />
                      {t.allergen[allergen]}
                    </label>
                  ))}
                </div>
              </fieldset>

              <h3>{t.profile.ingredientsHeading}</h3>
              <IngredientListEditor
                id="white-list"
                label={t.profile.whiteList}
                hint={t.profile.whiteListHint}
                items={whiteList}
                onAdd={addPreferred}
                onRemove={(name) => {
                  setWhiteList((list) => list.filter((item) => item !== name))
                  setSaveState('idle')
                }}
              />
              <IngredientListEditor
                id="black-list"
                label={t.profile.blackList}
                hint={t.profile.blackListHint}
                items={blackList}
                onAdd={addDisliked}
                onRemove={(name) => {
                  setBlackList((list) => list.filter((item) => item !== name))
                  setSaveState('idle')
                }}
              />

              <div className="profile-actions">
                <button
                  type="button"
                  className="button-primary"
                  onClick={handleSave}
                  disabled={saveState === 'saving'}
                >
                  {saveState === 'saving' ? t.profile.saving : t.profile.save}
                </button>
                <button
                  type="button"
                  className="button-quiet"
                  onClick={handleCancel}
                  disabled={saveState === 'saving'}
                >
                  {t.profile.cancel}
                </button>
                {saveState === 'error' && (
                  <span role="alert" className="form-error">
                    {t.profile.saveFailed}
                  </span>
                )}
              </div>
            </>
          ) : (
            <>
              <dl className="figure-list">
                <div>
                  <dt>{t.profile.diet}</dt>
                  <dd>{t.diet[user.dietType]}</dd>
                </div>
                <div>
                  <dt>{t.profile.allergens}</dt>
                  <dd>{listOrNone(user.allergens.map((a) => t.allergen[a]))}</dd>
                </div>
                <div>
                  <dt>{t.profile.whiteList}</dt>
                  <dd>{listOrNone(user.whiteList)}</dd>
                </div>
                <div>
                  <dt>{t.profile.blackList}</dt>
                  <dd>{listOrNone(user.blackList)}</dd>
                </div>
                <div>
                  <dt>{t.profile.cuisines}</dt>
                  <dd>{listOrNone(user.cuisines)}</dd>
                </div>
                <div>
                  <dt>{t.profile.household}</dt>
                  <dd>{t.profile.householdValue(user.householdSize)}</dd>
                </div>
                <div>
                  <dt>{t.profile.budget}</dt>
                  <dd>{budget !== null ? formatPrice(budget) : t.profile.notSet}</dd>
                </div>
                <div>
                  <dt>{t.profile.market}</dt>
                  <dd>{user.market ?? t.profile.notSet}</dd>
                </div>
                <div>
                  <dt>{t.profile.age}</dt>
                  <dd>{user.age ?? t.profile.notSet}</dd>
                </div>
                <div>
                  <dt>{t.profile.gender}</dt>
                  <dd>{user.gender ?? t.profile.notSet}</dd>
                </div>
              </dl>
            </>
          )}
          {/* Always mounted, so screen readers announce the change. */}
          <p role="status" className="muted profile-status">
            {!editing && saveState === 'saved' && t.profile.saved}
          </p>
        </section>

        <div className="detail-side">
          <section className="card">
            <h2>{t.profile.thisWeek}</h2>
            <dl className="figure-list">
              <div>
                <dt>{t.profile.recipesInPlan}</dt>
                <dd>{planned.length}</dd>
              </div>
              <div>
                <dt>{t.profile.basketTotal}</dt>
                <dd>{formatPrice(total)}</dd>
              </div>
            </dl>

            {budget !== null && (
              <>
                <div
                  className="budget-bar"
                  role="img"
                  aria-label={`${formatPrice(total)} of ${formatPrice(budget)}`}
                >
                  <span style={{ width: `${budgetUsed}%` }} />
                </div>
                <p className="muted budget-caption">
                  {formatPrice(total)} / {formatPrice(budget)}
                </p>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
