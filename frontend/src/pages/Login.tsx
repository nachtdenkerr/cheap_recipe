import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { signIn } from '../auth/session'
import { t } from '../i18n/strings'

interface RedirectState {
  from?: string
}

export function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()

    // The only validation the mockup does: the fields aren't empty.
    if (!email.trim()) {
      setError(t.login.emailRequired)
      return
    }
    if (!password) {
      setError(t.login.passwordRequired)
      return
    }

    signIn(email.trim())
    const from = (location.state as RedirectState | null)?.from
    navigate(from ?? '/', { replace: true })
  }

  return (
    <div className="login-page">
      <div className="login-panel">
        <div className="brand brand-large">
          <span className="brand-mark" aria-hidden="true">
            €
          </span>
          <span className="brand-name">{t.appName}</span>
        </div>
        <p className="login-tagline">{t.tagline}</p>

        <form className="login-form card" onSubmit={handleSubmit} noValidate>
          <h1>{t.login.heading}</h1>
          <p className="muted">{t.login.subheading}</p>

          <label htmlFor="email">{t.login.email}</label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            placeholder={t.login.emailPlaceholder}
            value={email}
            onChange={(event) => {
              setEmail(event.target.value)
              setError(null)
            }}
          />

          <label htmlFor="password">{t.login.password}</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            placeholder="••••••••"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value)
              setError(null)
            }}
          />

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" className="button-primary">
            {t.login.submit}
          </button>

          <p className="notice">{t.login.mockNotice}</p>
        </form>
      </div>
    </div>
  )
}
