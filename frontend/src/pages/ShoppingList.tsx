import { useEffect, useMemo, useState } from 'react'

import { OFFER_WEEK_START, fetchShoppingList, setChecked, uncheckAll as uncheckAllItems } from '../api/client'
import type { ShoppingListItem } from '../api/types'
import { LoadError, loadErrorText } from '../components/LoadError'
import { formatCost, formatPrice, formatWeekday, startsLate } from '../format'
import { t } from '../i18n/strings'

/**
 * Shop by aisle, not by recipe — group the list the way the store is laid out.
 * Offers go under their department; everything bought at the regular price
 * comes last, in one group of its own.
 */
function byCategory(items: ShoppingListItem[]): [string, ShoppingListItem[]][] {
  const groups = new Map<string, ShoppingListItem[]>()
  const regular: ShoppingListItem[] = []

  for (const item of items) {
    if (!item.offer) {
      regular.push(item)
      continue
    }
    const category = item.offer.category ?? t.shopping.otherCategory
    const existing = groups.get(category)
    if (existing) {
      existing.push(item)
    } else {
      groups.set(category, [item])
    }
  }

  const sorted = [...groups.entries()].sort(([a], [b]) => a.localeCompare(b, 'de'))
  return regular.length > 0 ? [...sorted, [t.shopping.notOnOffer, regular]] : sorted
}

/** A line's price: the offer's, an estimate, or null when neither is known. */
function linePrice(item: ShoppingListItem): number | null {
  if (item.offer) return item.offer.priceCents * item.quantity
  return item.estimatedPriceCents ?? null
}

/** Offers exact, the rest estimated; how many lines have no price at all. */
function sumPrices(items: ShoppingListItem[]) {
  let cents = 0
  let estimated = 0
  let unpriced = 0
  for (const item of items) {
    const price = linePrice(item)
    if (price === null) unpriced += 1
    else {
      cents += price
      if (!item.offer) estimated += price
    }
  }
  return { cents, estimated, unpriced }
}

export function ShoppingList() {
  const [loadError, setLoadError] = useState<string | null>(null)
  const [items, setItems] = useState<ShoppingListItem[] | null>(null)

  useEffect(() => {
    let active = true
    fetchShoppingList()
      .then((result) => {
        if (active) setItems(result)
      })
      .catch((error) => active && setLoadError(loadErrorText(error)))
    return () => {
      active = false
    }
  }, [])

  const groups = useMemo(() => byCategory(items ?? []), [items])
  const manyMarkets = useMemo(
    () => new Set((items ?? []).flatMap((i) => (i.offer?.market ? [i.offer.market] : []))).size > 1,
    [items],
  )

  function setLine(id: number, checked: boolean) {
    setItems(
      (current) => current?.map((item) => (item.id === id ? { ...item, checked } : item)) ?? null,
    )
  }

  // Shown at once, then saved; put back if the save fails.
  async function toggle(item: ShoppingListItem) {
    setLine(item.id, !item.checked)
    try {
      await setChecked(item.id, !item.checked)
    } catch {
      setLine(item.id, item.checked)
    }
  }

  async function uncheckAll() {
    const before = items
    setItems((current) => current?.map((item) => ({ ...item, checked: false })) ?? null)
    try {
      await uncheckAllItems()
    } catch {
      setItems(before)
    }
  }

  if (loadError) {
    return <LoadError message={loadError} />
  }

  if (!items) {
    return <p className="muted">{t.common.loading}</p>
  }

  const total = sumPrices(items)
  const collected = sumPrices(items.filter((item) => item.checked))
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
          <span className="stat-value">
            {formatCost(total.cents, total.unpriced, total.estimated)}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">{t.shopping.checkedTotal}</span>
          <span className="stat-value">
            {formatCost(collected.cents, collected.unpriced, collected.estimated)}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">{t.shopping.remaining}</span>
          <span className="stat-value">{remaining}</span>
        </div>
      </section>
      {total.estimated > 0 && <p className="meta">{t.shopping.totalHint}</p>}

      {items.length === 0 ? (
        <p className="muted">{t.shopping.empty}</p>
      ) : (
        groups.map(([category, categoryItems]) => (
          <section key={category} className="card list-group">
            <h2 className="list-group-title">{category}</h2>
            <ul className="shopping-list">
              {categoryItems.map((item) => (
                <ShoppingLine
                  key={item.id}
                  item={item}
                  showMarket={manyMarkets}
                  onToggle={() => toggle(item)}
                />
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  )
}

function ShoppingLine({
  item,
  showMarket,
  onToggle,
}: {
  item: ShoppingListItem
  /** Name the branch — only worth it when the list spans several. */
  showMarket: boolean
  onToggle: () => void
}) {
  const { offer } = item
  const price = linePrice(item)

  return (
    <li className={item.checked ? 'shopping-item done' : 'shopping-item'}>
      <label>
        <input type="checkbox" checked={item.checked} onChange={onToggle} />
        <span className="shopping-item-body">
          <span className="shopping-item-title">{offer ? offer.title : item.name}</span>
          <span className="shopping-item-meta">
            {offer ? offer.ingredientEn : item.amount}
            {showMarket && offer?.market && <span className="offer-market"> · {offer.market}</span>}
            {item.quantity > 1 && ` · ×${item.quantity}`}
            {!offer && ` · ${price === null ? t.shopping.noPrice : t.shopping.regularPrice}`}
          </span>
          {offer && startsLate(offer.validFrom, OFFER_WEEK_START) && (
            <span className="offer-late shopping-item-late">
              {t.recipe.availableFrom(formatWeekday(offer.validFrom!))}
            </span>
          )}
          <span className="shopping-item-used">
            {t.shopping.usedBy}: {item.usedBy.join(', ')}
          </span>
        </span>
        <span className={offer ? 'shopping-item-price' : 'shopping-item-price estimated'}>
          {price === null ? '—' : offer ? formatPrice(price) : t.price.approx(formatPrice(price))}
        </span>
      </label>
    </li>
  )
}
