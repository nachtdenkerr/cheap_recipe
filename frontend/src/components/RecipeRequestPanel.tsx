import { useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/client'
import type { RefineRequest } from '../api/types'
import { t } from '../i18n/strings'
import { IngredientListEditor } from './IngredientListEditor'

interface Props {
  open: boolean
  onClose: () => void
  /** Recipes on the page the user has not added to their meal plan. */
  unplannedCount: number
  remaining: number
  limit: number
  /** Sends the request; rejects with ApiError on failure. */
  onSubmit: (request: RefineRequest) => Promise<void>
}

/**
 * The "ask for new recipes" form, in a native modal <dialog>: the browser
 * provides the focus trap, Escape to close, and the backdrop.
 */
export function RecipeRequestPanel({
  open,
  onClose,
  unplannedCount,
  remaining,
  limit,
  onSubmit,
}: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [mode, setMode] = useState<RefineRequest['mode']>('replace')
  const [count, setCount] = useState(1)
  const [pantryItems, setPantryItems] = useState<string[]>([])
  const [note, setNote] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) {
      // Fresh form each time, starting from what the page suggests.
      setMode('replace')
      setCount(Math.min(Math.max(unplannedCount, 1), 5))
      setPantryItems([])
      setNote('')
      setError(null)
      dialog.showModal()
      // Start on the first choice rather than the close button.
      dialog.querySelector<HTMLInputElement>('input[name="request-mode"]')?.focus()
    } else if (!open && dialog.open) {
      dialog.close()
    }
  }, [open, unplannedCount])

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (mode === 'pantry' && pantryItems.length === 0) {
      setError(t.request.needItems)
      return
    }
    setSending(true)
    setError(null)
    try {
      await onSubmit({
        mode,
        count,
        pantryItems: mode === 'pantry' ? pantryItems : undefined,
        note: note.trim() || undefined,
      })
    } catch (caught) {
      const status = caught instanceof ApiError ? caught.status : 0
      setError(
        status === 429
          ? t.request.errorQuota
          : status === 409
            ? t.request.errorNoneFit
            : t.request.errorGeneric,
      )
    } finally {
      setSending(false)
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="request-dialog"
      aria-labelledby="request-heading"
      // Escape and the close button both end up here.
      onClose={onClose}
    >
      <form onSubmit={handleSubmit} className="request-form">
        <div className="request-head">
          <h2 id="request-heading">{t.request.heading}</h2>
          <button
            type="button"
            className="chip-remove request-close"
            aria-label={t.request.close}
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <p className="muted">{t.request.intro}</p>

        <fieldset className="choice-group">
          <legend>{t.request.whatDoYouNeed}</legend>
          <div className="choice-options">
            <label className="choice">
              <input
                type="radio"
                name="request-mode"
                checked={mode === 'replace'}
                onChange={() => setMode('replace')}
              />
              {t.request.replace(unplannedCount)}
            </label>
            <label className="choice">
              <input
                type="radio"
                name="request-mode"
                checked={mode === 'pantry'}
                onChange={() => setMode('pantry')}
              />
              {t.request.pantry}
            </label>
          </div>
        </fieldset>

        {mode === 'pantry' && (
          <IngredientListEditor
            id="pantry-items"
            label={t.request.pantryLabel}
            hint={t.request.pantryHint}
            items={pantryItems}
            onAdd={(name) => {
              setPantryItems((list) => (list.includes(name) ? list : [...list, name]))
              setError(null)
            }}
            onRemove={(name) => setPantryItems((list) => list.filter((item) => item !== name))}
          />
        )}

        <div className="request-field">
          <label htmlFor="request-count">{t.request.count}</label>
          <input
            id="request-count"
            type="number"
            min={1}
            max={5}
            value={count}
            onChange={(event) =>
              setCount(Math.min(Math.max(Number(event.target.value) || 1, 1), 5))
            }
          />
        </div>

        <div className="request-field">
          <label htmlFor="request-note">{t.request.note}</label>
          <textarea
            id="request-note"
            rows={2}
            maxLength={300}
            placeholder={t.request.notePlaceholder}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </div>

        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}

        <p className="meta">{t.request.usage(remaining, limit)}</p>

        <div className="profile-actions request-actions">
          <button type="submit" className="button-primary" disabled={sending}>
            {sending ? t.request.sending : t.request.send}
          </button>
          <button type="button" className="button-quiet" onClick={onClose} disabled={sending}>
            {t.request.cancel}
          </button>
        </div>
      </form>
    </dialog>
  )
}
