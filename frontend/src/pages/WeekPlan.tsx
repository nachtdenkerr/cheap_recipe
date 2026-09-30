import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { fetchWeekPlan } from '../api/client'
import type { PlannedMeal, WeekPlan as Week } from '../api/types'
import { LoadError, loadErrorText } from '../components/LoadError'
import { formatDate } from '../format'
import { t } from '../i18n/strings'

function Meal({ meal }: { meal: PlannedMeal | undefined }) {
  if (!meal?.recipeId) {
    return <span className="week-empty">{t.week.nothing}</span>
  }
  return (
    <>
      <Link to={`/recipes/${meal.recipeId}`} className="week-recipe">
        {meal.title}
      </Link>
      {meal.leftover && <span className="week-leftover">{t.week.leftovers}</span>}
    </>
  )
}

/**
 * The week grid: a table on wide screens (days across, meals down) and one
 * block per day on narrow ones — the same data, both rendered, CSS picks.
 */
export function WeekPlan() {
  const [week, setWeek] = useState<Week | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    fetchWeekPlan()
      .then((result) => active && setWeek(result))
      .catch((error) => active && setLoadError(loadErrorText(error)))
    return () => {
      active = false
    }
  }, [])

  if (loadError) return <LoadError message={loadError} />
  if (!week) return <p className="muted">{t.common.loading}</p>

  const planned = week.days.some((day) => day.meals.some((meal) => meal.recipeId))
  const mealOf = (dayIndex: number, meal: string) =>
    week.days[dayIndex].meals.find((m) => m.meal === meal)

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{t.week.heading}</h1>
          <p className="muted">{t.week.subheading(week.householdSize)}</p>
        </div>
      </header>

      {!planned ? (
        <div className="card week-none">
          <p>{t.week.empty}</p>
          <Link className="button-primary" to="/">
            {t.week.toRecipes}
          </Link>
        </div>
      ) : (
        <>
          <div className="card week-table-wrap">
            <table className="week-table">
              <thead>
                <tr>
                  <td />
                  {week.days.map((day) => (
                    <th key={day.day} scope="col">
                      {t.week.day[day.day]}
                      <span className="meta">{formatDate(day.date)}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {week.mealTypes.map((meal) => (
                  <tr key={meal}>
                    <th scope="row">{t.meal[meal]}</th>
                    {week.days.map((day, index) => (
                      <td key={day.day}>
                        <Meal meal={mealOf(index, meal)} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <ol className="week-days">
            {week.days.map((day) => (
              <li key={day.day} className="card week-day">
                <h2>
                  {t.week.day[day.day]} <span className="meta">{formatDate(day.date)}</span>
                </h2>
                <dl>
                  {day.meals.map((meal) => (
                    <div key={meal.meal}>
                      <dt>{t.meal[meal.meal]}</dt>
                      <dd>
                        <Meal meal={meal} />
                      </dd>
                    </div>
                  ))}
                </dl>
              </li>
            ))}
          </ol>

          <div className="week-notes muted">
            {week.emptyMeals > 0 && <p>{t.week.emptyMeals(week.emptyMeals)}</p>}
            {week.spare.map((s) => (
              <p key={s.recipeId}>{t.week.spare(s.title, s.portions)}</p>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
