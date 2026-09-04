import { t } from '../i18n/strings'
import type { DietType } from '../api/types'

export function DietBadge({ diet }: { diet: DietType }) {
  return <span className={`badge badge-${diet}`}>{t.diet[diet]}</span>
}
