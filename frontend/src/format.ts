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
