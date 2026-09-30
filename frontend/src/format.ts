/** Display helpers. Prices are stored in cents; dates arrive as ISO strings. */

import { t } from './i18n/strings'

const euro = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' })
const shortDate = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' })
const weekday = new Intl.DateTimeFormat('en-GB', { weekday: 'long' })

export function formatPrice(cents: number): string {
  return euro.format(cents / 100)
}

export function formatDate(iso: string): string {
  return shortDate.format(new Date(iso))
}

export function formatWeekday(iso: string): string {
  return weekday.format(new Date(iso))
}

/** A duration in minutes as "45 min", "1 h" or "1 h 30 min". */
export function formatMinutes(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours === 0) return `${rest} min`
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`
}

/**
 * A cost that may be a floor or an estimate:
 *
 * - "from 8,90 €" when some items have no price at all — the true cost is at
 *   least this;
 * - "≈ 12,40 €" when every item is priced but some only at an estimated
 *   regular price;
 * - "11,46 €" when everything is on offer.
 */
export function formatCost(cents: number, unpricedCount: number, estimatedCents = 0): string {
  if (unpricedCount > 0) return t.price.from(formatPrice(cents))
  if (estimatedCents > 0) return t.price.approx(formatPrice(cents))
  return formatPrice(cents)
}

/** Whether an offer only starts after the week began ("From Thursday"). */
export function startsLate(validFrom: string | null | undefined, weekStart: string): boolean {
  return Boolean(validFrom) && validFrom! > weekStart
}
