/** Display helpers. Prices are stored in cents; dates arrive as ISO strings. */

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
