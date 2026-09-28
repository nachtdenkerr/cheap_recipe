import { DAY_MINUTE_OPTIONS, DEFAULT_DAY_MINUTES, WEEKDAYS } from '../api/vocabulary'
import { formatMinutes } from '../format'
import { t } from '../i18n/strings'

/**
 * Cooking time per day, in a collapsible <details> so the section stays out
 * of the way until someone opens it. The planner leaves out recipes too long
 * for any day, and the critic checks the whole week against these times.
 */

function dayLabel(minutes: number): string {
  return minutes === 0 ? t.weekTime.noCooking : formatMinutes(minutes)
}

function weekSummary(week: number[] | null): string {
  if (!week) return t.profile.notSet
  const total = week.reduce((sum, minutes) => sum + minutes, 0)
  return t.weekTime.perWeek(formatMinutes(total))
}

/** Read-only: the week at a glance, days listed when opened. */
export function WeekTimeSummary({ week }: { week: number[] | null }) {
  return (
    <details className="week-time">
      <summary>
        <span className="week-time-title">{t.weekTime.heading}</span>
        <span className="muted">{weekSummary(week)}</span>
      </summary>
      {week ? (
        <dl className="figure-list week-time-days">
          {WEEKDAYS.map((day, index) => (
            <div key={day}>
              <dt>{t.weekTime.day[day]}</dt>
              <dd>{dayLabel(week[index])}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="muted">{t.weekTime.unsetHint}</p>
      )}
    </details>
  )
}

interface EditorProps {
  week: number[] | null
  onChange: (week: number[] | null) => void
}

/** Editable: one dropdown per day, 15-minute steps up to 24 h. */
export function WeekTimeEditor({ week, onChange }: EditorProps) {
  return (
    <details className="week-time">
      <summary>
        <span className="week-time-title">{t.weekTime.heading}</span>
        <span className="muted">{weekSummary(week)}</span>
      </summary>

      <p className="meta">{t.weekTime.hint}</p>

      {week ? (
        <>
          <div className="week-time-grid">
            {WEEKDAYS.map((day, index) => (
              <div key={day} className="week-time-field">
                <label htmlFor={`week-time-${day}`}>{t.weekTime.day[day]}</label>
                <select
                  id={`week-time-${day}`}
                  value={week[index]}
                  onChange={(event) =>
                    onChange(
                      week.map((minutes, i) => (i === index ? Number(event.target.value) : minutes)),
                    )
                  }
                >
                  {DAY_MINUTE_OPTIONS.map((minutes) => (
                    <option key={minutes} value={minutes}>
                      {dayLabel(minutes)}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          <button type="button" className="button-quiet" onClick={() => onChange(null)}>
            {t.weekTime.clear}
          </button>
        </>
      ) : (
        <>
          <p className="muted">{t.weekTime.unsetHint}</p>
          <button
            type="button"
            className="button-quiet"
            onClick={() => onChange(WEEKDAYS.map(() => DEFAULT_DAY_MINUTES))}
          >
            {t.weekTime.set}
          </button>
        </>
      )}
    </details>
  )
}
