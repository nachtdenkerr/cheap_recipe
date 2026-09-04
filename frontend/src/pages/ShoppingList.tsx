import { useEffect, useMemo, useState } from 'react'

import { fetchShoppingList } from '../api/client'
import type { ShoppingListItem } from '../api/types'
import { formatPrice, formatWeekday } from '../format'
import { t } from '../i18n/strings'

const WEEK_START = '2025-11-17'

/** Shop by aisle, not by recipe — group the list the way the store is laid out. */
function byCategory(items: ShoppingListItem[]): [string, ShoppingListItem[]][] {
  const groups = new Map<string, ShoppingListItem[]>()

  for (const item of items) {
    const existing = groups.get(item.offer.category)
    if (existing) {
      existing.push(item)
    } else {
      groups.set(item.offer.category, [item])
    }
  }

  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b, 'de'))
}

export function ShoppingList() {
  const [items, setItems] = useState<ShoppingListItem[] | null>(null)

  useEffect(() => {
    let active = true
    fetchShoppingList().then((result) => {
      if (active) setItems(result)
    })
    return () => {
      active = false
    }
  }, [])

  const groups = useMemo(() => byCategory(items ?? []), [items])

  function toggle(offerTitle: string) {
    setItems((current) =>
      current?.map((item) =>
        item.offer.title === offerTitle ? { ...item, checked: !item.checked } : item,
      ) ?? null,
    )
  }

  function uncheckAll() {
    setItems((current) => current?.map((item) => ({ ...item, checked: false })) ?? null)
  }

  if (!items) {
    return <p className="muted">{t.common.loading}</p>
  }

  const total = items.reduce((sum, item) => sum + item.offer.priceCents * item.quantity, 0)
  const collected = items
    .filter((item) => item.checked)
    .reduce((sum, item) => sum + item.offer.priceCents * item.quantity, 0)
  const recipeCount = new Set(items.flatMap((item) => item.usedBy)).size
  const remaining = items.filter((item) => !item.checked).length

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{t.shopping.heading}</h1>
          <p className="muted">{t.shopping.subheading(items.length, recipeCount)}</p>
        </div>
        <button type="button" className="button-quiet" onClick={uncheckAll}>
          {t.shopping.clearChecked}
        </button>
      </header>

      <section className="stat-row">
        <div className="stat">
          <span className="stat-label">{t.shopping.total}</span>
          <span className="stat-value">{formatPrice(total)}</span>
        </div>
        <div className="stat">
          <span className="stat-label">{t.shopping.checkedTotal}</span>
          <span className="stat-value">{formatPrice(collected)}</span>
        </div>
        <div className="stat">
          <span className="stat-label">{t.shopping.remaining}</span>
          <span className="stat-value">{remaining}</span>
        </div>
      </section>

      {items.length === 0 ? (
        <p className="muted">{t.shopping.empty}</p>
      ) : (
        groups.map(([category, categoryItems]) => (
          <section key={category} className="card list-group">
            <h2 className="list-group-title">{category}</h2>
            <ul className="shopping-list">
              {categoryItems.map((item) => (
                <li key={item.offer.title} className={item.checked ? 'shopping-item done' : 'shopping-item'}>
                  <label>
                    <input
                      type="checkbox"
                      checked={item.checked}
                      onChange={() => toggle(item.offer.title)}
                    />
                    <span className="shopping-item-body">
                      <span className="shopping-item-title">{item.offer.title}</span>
                      <span className="shopping-item-meta">
                        {item.offer.ingredientEn}
                        {item.quantity > 1 && ` · ×${item.quantity}`}
                        {item.offer.validFrom > WEEK_START &&
                          ` · ${t.recipe.availableFrom(formatWeekday(item.offer.validFrom))}`}
                      </span>
                      <span className="shopping-item-used">
                        {t.shopping.usedBy}: {item.usedBy.join(', ')}
                      </span>
                    </span>
                    <span className="shopping-item-price">
                      {formatPrice(item.offer.priceCents * item.quantity)}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  )
}
