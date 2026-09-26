import { NavLink, Outlet } from 'react-router-dom'

import { t } from '../i18n/strings'
import { UserMenu } from './UserMenu'

export function Layout() {
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
        </nav>

        <UserMenu />
      </header>

      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
