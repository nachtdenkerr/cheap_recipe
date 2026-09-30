import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { ApiError, USE_MOCK, login, signup } from '../api/client'
import { saveSession } from '../auth/session'
import { t } from '../i18n/strings'

interface RedirectState {
  from?: string
}

type Mode = 'signin' | 'signup'

// What POST /auth/signup accepts (backend app/schemas/auth.py), checked here
// first so the message is specific.
const USERNAME = /^.{3,30}$/
const PASSWORD_MIN = 8

export function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const [mode, setMode] = useState<Mode>('signin')
  const [name, setName] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const signingUp = mode === 'signup'

  function validate(): string | null {
    if (!email.trim()) return t.login.emailRequired
    if (!password) return t.login.passwordRequired
    if (signingUp && !USERNAME.test(username.trim())) return t.login.usernameInvalid
    if (signingUp && password.length < PASSWORD_MIN) return t.login.passwordTooShort(PASSWORD_MIN)
    return null
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const invalid = validate()
    if (invalid) {
      setError(invalid)
      return
    }

    setBusy(true)
    try {
      const session = signingUp
        ? await signup({
            username: username.trim(),
            email: email.trim(),
            password,
            name: name.trim() || undefined,
          })
        : await login(email.trim(), password)
      saveSession(session.token, session.user.email)
      const from = (location.state as RedirectState | null)?.from
      navigate(from ?? '/', { replace: true })
    } catch (caught) {
      setError(errorText(caught, signingUp))
    } finally {
      setBusy(false)
    }
  }

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
  }

  function field(setter: (value: string) => void) {
    return (event: React.ChangeEvent<HTMLInputElement>) => {
      setter(event.target.value)
      setError(null)
    }
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
          <h1>{signingUp ? t.login.signupHeading : t.login.heading}</h1>
          <p className="muted">{signingUp ? t.login.signupSubheading : t.login.subheading}</p>

          {signingUp && (
            <>
              <label htmlFor="name">{t.login.name}</label>
              <input
                id="name"
                name="name"
                autoComplete="name"
                value={name}
                onChange={field(setName)}
              />

              <label htmlFor="username">{t.login.username}</label>
              <input
                id="username"
                name="username"
                autoComplete="username"
                value={username}
                onChange={field(setUsername)}
              />
            </>
          )}

          <label htmlFor="email">{t.login.email}</label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            placeholder={t.login.emailPlaceholder}
            value={email}
            onChange={field(setEmail)}
          />

          <label htmlFor="password">{t.login.password}</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete={signingUp ? 'new-password' : 'current-password'}
            placeholder="••••••••"
            value={password}
            onChange={field(setPassword)}
          />

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" className="button-primary" disabled={busy}>
            {busy ? t.login.working : signingUp ? t.login.signupSubmit : t.login.submit}
          </button>

          <p className="muted login-switch">
            {signingUp ? t.login.haveAccount : t.login.noAccount}{' '}
            <button
              type="button"
              className="link-button"
              onClick={() => switchMode(signingUp ? 'signin' : 'signup')}
            >
              {signingUp ? t.login.toSignin : t.login.toSignup}
            </button>
          </p>

          {USE_MOCK && <p className="notice">{t.login.mockNotice}</p>}
        </form>
      </div>
    </div>
  )
}

function errorText(caught: unknown, signingUp: boolean): string {
  if (!(caught instanceof ApiError)) return t.login.failed
  if (caught.status === 0) return t.login.unreachable
  if (caught.status === 401) return t.login.wrongCredentials
  if (caught.status === 409) return t.login.taken
  if (caught.status === 422) return signingUp ? t.login.checkFields : t.login.wrongCredentials
  return t.login.failed
}
