import { useEffect, useId, useState } from 'react'

import { searchMarkets } from '../api/client'
import type { Market } from '../api/types'
import { MAX_HOME_MARKETS } from '../api/vocabulary'
import { t } from '../i18n/strings'

interface Props {
  markets: Market[]
  onChange: (markets: Market[]) => void
}

/** How long typing must pause before a search is sent. */
const DEBOUNCE_MS = 300
const MIN_CHARS = 2

export function marketLine(market: Market): string {
  const place = [market.postalCode, market.city].filter(Boolean).join(' ')
  return [market.street, place].filter(Boolean).join(', ')
}

type Search =
  | { state: 'idle' }
  | { state: 'searching' }
  | { state: 'done'; results: Market[] }
  | { state: 'failed' }

/**
 * The home supermarkets: chips for the chosen ones, and a search box whose
 * results are a combobox listbox — arrow keys move, Enter adds, Escape closes.
 */
export function MarketPicker({ markets, onChange }: Props) {
  const id = useId()
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState<Search>({ state: 'idle' })
  const [active, setActive] = useState(-1)

  useEffect(() => {
    const trimmed = query.trim()
    if (trimmed.length < MIN_CHARS) {
      setSearch({ state: 'idle' })
      return
    }
    let current = true
    const timer = setTimeout(() => {
      setSearch({ state: 'searching' })
      searchMarkets(trimmed)
        .then((results) => current && setSearch({ state: 'done', results }))
        .catch(() => current && setSearch({ state: 'failed' }))
    }, DEBOUNCE_MS)
    setActive(-1)
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [query])

  const results = search.state === 'done' ? search.results : []
  const chosen = new Set(markets.map((m) => m.id))
  const full = markets.length >= MAX_HOME_MARKETS
  const open = search.state !== 'idle' && !full

  function add(market: Market) {
    if (!chosen.has(market.id) && !full) onChange([...markets, market])
    setQuery('')
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' && results.length > 0) {
      event.preventDefault()
      setActive((i) => (i + 1) % results.length)
    } else if (event.key === 'ArrowUp' && results.length > 0) {
      event.preventDefault()
      setActive((i) => (i <= 0 ? results.length - 1 : i - 1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const pick = results[active] ?? (results.length === 1 ? results[0] : undefined)
      if (pick) add(pick)
    } else if (event.key === 'Escape' && query) {
      // Clear the search, not the whole form (a surrounding dialog, say).
      event.stopPropagation()
      setQuery('')
    }
  }

  return (
    <div className="list-editor market-picker">
      <label htmlFor={`${id}-input`}>{t.profile.markets}</label>
      <p className="meta" id={`${id}-hint`}>
        {t.profile.marketsHint}
      </p>

      {markets.length > 0 ? (
        <ul className="chip-list">
          {markets.map((market) => (
            <li key={market.id} className="chip chip-removable">
              {market.name}
              {market.city && <span className="chip-detail">{market.city}</span>}
              <button
                type="button"
                className="chip-remove"
                aria-label={t.profile.removeMarket(market.name)}
                onClick={() => onChange(markets.filter((m) => m.id !== market.id))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="form-error">{t.profile.marketsRequired}</p>
      )}

      {full ? (
        <p className="meta">{t.profile.marketsFull(MAX_HOME_MARKETS)}</p>
      ) : (
      <div className="market-search">
        <input
          id={`${id}-input`}
          type="search"
          role="combobox"
          autoComplete="off"
          aria-expanded={open && results.length > 0}
          aria-controls={`${id}-results`}
          aria-activedescendant={active >= 0 ? `${id}-option-${active}` : undefined}
          aria-describedby={`${id}-hint`}
          value={query}
          maxLength={80}
          placeholder={t.profile.marketPlaceholder}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={onKeyDown}
        />
        {open && (
          <div className="market-results">
            <ul id={`${id}-results`} role="listbox" aria-label={t.profile.marketSearch}>
              {results.map((market, index) => {
                const added = chosen.has(market.id)
                return (
                  <li
                    key={market.id}
                    id={`${id}-option-${index}`}
                    role="option"
                    aria-selected={index === active}
                    aria-disabled={added}
                    className={index === active ? 'is-active' : undefined}
                    // mousedown, so the input keeps focus for the next search
                    onMouseDown={(event) => {
                      event.preventDefault()
                      add(market)
                    }}
                  >
                    <span className="market-name">{market.name}</span>
                    <span className="meta">{marketLine(market)}</span>
                    {added && <span className="market-added">{t.profile.marketAdded}</span>}
                  </li>
                )
              })}
            </ul>
            <p className="meta market-status" role="status">
              {search.state === 'searching' && t.profile.marketSearching}
              {search.state === 'failed' && t.profile.marketSearchFailed}
              {search.state === 'done' &&
                (results.length === 0 ? t.profile.marketNoResults : t.profile.marketResults(results.length))}
            </p>
          </div>
        )}
      </div>
      )}
    </div>
  )
}
