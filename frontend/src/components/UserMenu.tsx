import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { getSession, signOut } from '../auth/session'
import { t } from '../i18n/strings'

/**
 * Round avatar button in the header that opens the account menu, like
 * GitHub's: who is signed in, a link to the profile, and sign out.
 *
 * Follows the menu-button pattern: Escape closes and returns focus to the
 * button, arrow keys move between items, and a click outside closes it.
 */
export function UserMenu() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const email = getSession()?.email ?? ''
  const initial = email.charAt(0).toUpperCase() || '?'

  function items(): HTMLElement[] {
    return [...(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])]
  }

  function close(returnFocus: boolean) {
    setOpen(false)
    if (returnFocus) buttonRef.current?.focus()
  }

  // Close on a click anywhere outside the menu.
  useEffect(() => {
    if (!open) return
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  // Put focus in the menu when it opens, so the keyboard can reach it.
  useEffect(() => {
    if (open) items()[0]?.focus()
  }, [open])

  function onMenuKeyDown(event: React.KeyboardEvent) {
    const list = items()
    const index = list.indexOf(document.activeElement as HTMLElement)
    switch (event.key) {
      case 'Escape':
        event.preventDefault()
        close(true)
        break
      case 'ArrowDown':
        event.preventDefault()
        list[(index + 1) % list.length]?.focus()
        break
      case 'ArrowUp':
        event.preventDefault()
        list[(index - 1 + list.length) % list.length]?.focus()
        break
      case 'Home':
        event.preventDefault()
        list[0]?.focus()
        break
      case 'End':
        event.preventDefault()
        list[list.length - 1]?.focus()
        break
      case 'Tab':
        close(false)
        break
    }
  }

  function handleSignOut() {
    signOut()
    navigate('/login', { replace: true })
  }

  return (
    <div className="user-menu" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className={pathname === '/profile' ? 'avatar-button current' : 'avatar-button'}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls="user-menu-list"
        aria-label={t.nav.accountMenu}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="avatar" aria-hidden="true">
          {initial}
        </span>
        <span className="avatar-caret" aria-hidden="true">
          ▾
        </span>
      </button>

      {open && (
        <div
          ref={menuRef}
          id="user-menu-list"
          className="menu"
          role="menu"
          aria-label={t.nav.accountMenu}
          onKeyDown={onMenuKeyDown}
        >
          <div className="menu-header">
            <span className="muted">{t.nav.signedInAs}</span>
            <span className="menu-email">{email}</span>
          </div>
          <Link
            to="/profile"
            role="menuitem"
            className="menu-item"
            tabIndex={-1}
            onClick={() => close(false)}
          >
            {t.nav.profile}
          </Link>
          <button
            type="button"
            role="menuitem"
            className="menu-item"
            tabIndex={-1}
            onClick={handleSignOut}
          >
            {t.nav.signOut}
          </button>
        </div>
      )}
    </div>
  )
}
