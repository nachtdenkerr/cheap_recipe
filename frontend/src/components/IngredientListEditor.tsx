import { useState } from 'react'

import { t } from '../i18n/strings'

interface Props {
  id: string
  label: string
  hint: string
  items: string[]
  onAdd: (name: string) => void
  onRemove: (name: string) => void
}

/** A list of ingredient chips with a field to add more; Enter adds. */
export function IngredientListEditor({ id, label, hint, items, onAdd, onRemove }: Props) {
  const [draft, setDraft] = useState('')

  function add() {
    const name = draft.trim().toLowerCase()
    if (name) onAdd(name)
    setDraft('')
  }

  return (
    <div className="list-editor">
      <label htmlFor={id}>{label}</label>
      <p className="meta" id={`${id}-hint`}>
        {hint}
      </p>

      {items.length > 0 ? (
        <ul className="chip-list">
          {items.map((name) => (
            <li key={name} className="chip chip-removable">
              {name}
              <button
                type="button"
                className="chip-remove"
                aria-label={t.profile.removeIngredient(name)}
                onClick={() => onRemove(name)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">{t.profile.noIngredients}</p>
      )}

      <div className="list-editor-add">
        <input
          id={id}
          type="text"
          value={draft}
          maxLength={80}
          placeholder={t.profile.ingredientPlaceholder}
          aria-describedby={`${id}-hint`}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              add()
            }
          }}
        />
        <button type="button" className="button-quiet" onClick={add} disabled={!draft.trim()}>
          {t.profile.addIngredient}
        </button>
      </div>
    </div>
  )
}
