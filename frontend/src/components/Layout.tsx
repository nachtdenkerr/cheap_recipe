import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { signOut } from '../auth/session'
import { t } from '../i18n/strings'

export function Layout() {
  const navigate = useNavigate()

  function handleSignOut() {
    signOut()
    navigate('/login', { replace: true })
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <NavLink to="/" className="brand">
          <span className="brand-mark" aria-hidden="true">
            €
          </span>
          <span className="brand-name">{t.appName}</span>
        </NavLink>

        <nav className="app-nav">
          <NavLink to="/" end>
            {t.nav.home}
          </NavLink>
          <NavLink to="/shopping-list">{t.nav.shoppingList}</NavLink>
          <NavLink to="/profile">{t.nav.profile}</NavLink>
        </nav>

        <button type="button" className="button-quiet" onClick={handleSignOut}>
          {t.nav.signOut}
        </button>
      </header>

      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
