import { ApiError } from '../api/client'
import { t } from '../i18n/strings'

/** What to tell the user when a page's data did not load. */
export function loadErrorText(error: unknown): string {
  return error instanceof ApiError && error.status === 0 ? t.common.unreachable : t.common.loadFailed
}

export function LoadError({ message }: { message: string }) {
  return (
    <p className="form-error" role="alert">
      {message}
    </p>
  )
}
