import { useEffect, useMemo, useState } from 'react'

import { t } from '../i18n/strings'

// What drops into the bowl while the planner and critic work.
const INGREDIENTS = ['🥕', '🧅', '🍅', '🥔', '🧄', '🥦', '🌶️', '🧀', '🍗', '🍋', '🫑', '🍄']
// What comes out when the week is ready — one at random.
const DISHES = ['🍝', '🍲', '🥘', '🍛', '🥗', '🌮', '🍜', '🥧', '🍳', '🍱']

// Where each falling ingredient drops, across the bowl's opening (percent).
const LANES = [30, 58, 42, 70, 36, 64]

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  )
}

interface Props {
  /** The planning steps so far; the last is what is happening now. */
  steps: string[]
  /** Set when the plan is ready: the dish pops out, then `onRevealed`. */
  ready: boolean
  onRevealed: () => void
}

/**
 * A grey bowl that ingredients drop into and a spoon stirs, while a plan is
 * being made; the steps planning reports are read out below it. When the
 * plan is ready a dish rises out of the bowl and fades, and then the page
 * shows the recipes. Decorative motion is hidden from screen readers; the
 * step text is a live region. With reduced motion there is no animation.
 */
export function PlanningBowl({ steps, ready, onRevealed }: Props) {
  const dish = useMemo(() => DISHES[Math.floor(Math.random() * DISHES.length)], [])
  // A different handful of ingredients each time.
  const [drops] = useState(() =>
    [...INGREDIENTS].sort(() => Math.random() - 0.5).slice(0, LANES.length),
  )
  const still = prefersReducedMotion()

  useEffect(() => {
    // Without the animation there is no animationend to wait for.
    if (ready && still) {
      const timer = setTimeout(onRevealed, 400)
      return () => clearTimeout(timer)
    }
  }, [ready, still, onRevealed])

  const current = ready ? t.planning.ready : (steps[steps.length - 1] ?? t.planning.starting)

  return (
    <section className="planning" aria-labelledby="planning-heading">
      <h2 id="planning-heading" className="visually-hidden">
        {t.planning.heading}
      </h2>
      <div
        className={`bowl-scene${ready ? ' is-ready' : ''}${still ? ' is-still' : ''}`}
        aria-hidden="true"
      >
        <svg className="bowl-back" viewBox="0 0 200 110" width="200" height="110">
          <ellipse cx="100" cy="22" rx="94" ry="18" fill="var(--bowl-inside)" />
        </svg>

        {!ready &&
          drops.map((emoji, index) => (
            <span
              key={emoji}
              className="bowl-drop"
              style={{
                left: `${LANES[index]}%`,
                animationDelay: `${index * 0.55}s`,
              }}
            >
              {emoji}
            </span>
          ))}

        <svg className="bowl-spoon" viewBox="0 0 40 150" width="40" height="150">
          <rect x="17" y="0" width="6" height="104" rx="3" fill="var(--spoon)" />
          <ellipse cx="20" cy="124" rx="14" ry="22" fill="var(--spoon)" />
        </svg>

        <svg className="bowl-front" viewBox="0 0 200 110" width="200" height="110">
          <path
            d="M6 22 A94 18 0 0 0 194 22 C190 72 158 106 100 106 C42 106 10 72 6 22 Z"
            fill="var(--bowl)"
          />
          <path
            d="M6 22 A94 18 0 0 0 194 22"
            fill="none"
            stroke="var(--bowl-rim)"
            strokeWidth="4"
            strokeLinecap="round"
          />
        </svg>

        {ready && (
          <span className="bowl-dish" onAnimationEnd={onRevealed}>
            {dish}
          </span>
        )}
      </div>

      <p className="planning-step" role="status" aria-live="polite">
        {current}
      </p>
      {steps.length > 1 && (
        <ol className="planning-steps">
          {steps.slice(0, ready ? steps.length : -1).map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      )}
    </section>
  )
}
