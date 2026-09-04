import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { getSession } from '../auth/session'

/** Sends anyone without a (fake) session to the login page. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation()

  if (!getSession()) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <>{children}</>
}
