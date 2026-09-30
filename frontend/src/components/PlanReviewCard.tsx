import type { PlanReview } from '../api/types'
import { t } from '../i18n/strings'

/**
 * "Why this week": the critic's own judgement of the plan, and — when the
 * rounds ran out before it approved — what it still holds against it.
 */
export function PlanReviewCard({ review }: { review: PlanReview }) {
  if (review.passed === null) {
    return (
      <section className="card plan-review" aria-labelledby="plan-review-heading">
        <h2 id="plan-review-heading">{t.review.heading}</h2>
        <p className="muted">{t.review.unreviewed}</p>
      </section>
    )
  }
  return (
    <section
      className={review.passed ? 'card plan-review' : 'card plan-review is-open'}
      aria-labelledby="plan-review-heading"
    >
      <h2 id="plan-review-heading">{t.review.heading}</h2>
      {review.assessment && <p className="plan-review-assessment">{review.assessment}</p>}
      <p className="meta">
        {review.passed ? t.review.passed(review.rounds) : t.review.notPassed(review.rounds)}
      </p>
      {!review.passed && review.issues.length > 0 && (
        <>
          <h3>{t.review.stillOpen}</h3>
          <ul>
            {review.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </>
      )}
      {!review.passed && review.suggestions.length > 0 && (
        <>
          <h3>{t.review.tryInstead}</h3>
          <ul>
            {review.suggestions.map((suggestion) => (
              <li key={suggestion}>{suggestion}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
