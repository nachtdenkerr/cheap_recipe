# CheapRecipe — Design Tokens

One type system for the whole app. Two color palettes that share the same
semantic roles:

- **Standard** (Grocery Market) — the default look for the whole app.
- **Premium** (Berry Deli) — swapped in for the paid health tier only.

Swap is a single attribute on a wrapping element (e.g. `<html data-tier="premium">`).
Only the color tokens change between tiers; type, spacing, radius and shadow stay identical.

---

## 1. Typography

Single pairing across both tiers.

| Role | Family | Weights used | Notes |
|------|--------|--------------|-------|
| Headings / display | **Bricolage Grotesque** | 600, 700, 800 | Tighten tracking on large sizes (`-0.02em`). |
| Body / UI | **Inter** | 400, 500, 600, 700 | Buttons and stat numbers at 600. |

### Load (Google Fonts)

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700;12..96,800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
```

```css
--font-heading: "Bricolage Grotesque", system-ui, sans-serif;
--font-body: "Inter", system-ui, sans-serif;
```

### Type scale

| Token | Size (rem) | Weight | Line-height | Tracking | Family |
|-------|-----------|--------|-------------|----------|--------|
| `display` | 2.5 – 3.25 (`clamp(2.5rem,5vw,3.25rem)`) | 800 | 1.02 | -0.02em | Heading |
| `h1` | 2.0 | 700 | 1.1 | -0.02em | Heading |
| `h2` | 1.5 | 700 | 1.15 | -0.01em | Heading |
| `h3` (card title) | 1.375 | 700 | 1.15 | -0.01em | Heading |
| `body-lg` | 1.125 | 400 | 1.55 | 0 | Body |
| `body` | 1.0 | 400 | 1.5 | 0 | Body |
| `small` | 0.875 | 400/500 | 1.45 | 0 | Body |
| `xs` (labels) | 0.75 | 500 | 1.4 | 0 | Body |

Rules: headings in Bricolage, everything else in Inter. Numbers in stats/prices use
`font-variant-numeric: tabular-nums`. Body line length ≤ 72ch. Sentence case for
labels and buttons (no ALL-CAPS).

---

## 2. Color — semantic roles

Every color is referenced by role, never by hue, so the premium swap is transparent
to components.

| Role token | Meaning / where it's used |
|------------|---------------------------|
| `primary` | Brand + main action (primary buttons, active states, links). |
| `primary-contrast` | Text/icon on top of `primary`. |
| `deal` | Discount badges (`−40%`). |
| `save` | "What you save" — savings pills, health-positive signals. |
| `save-soft` | Tint background behind `save` text (pills, chips). |
| `accent` | Sparingly: highlights, small emphasis. Never a text-on background. |
| `bg` | App background. |
| `surface` | Cards, sheets, inputs. |
| `text` | Primary text. |
| `muted` | Secondary text, captions. |
| `border` | Hairline dividers, card borders, input outlines. |

---

## 3. Standard palette — Grocery Market (default)

| Role | Hex |
|------|-----|
| `primary` | `#D8382A` |
| `primary-contrast` | `#FFFFFF` |
| `deal` | `#D8382A` |
| `save` | `#5C7A3A` |
| `save-soft` | `#EEF2E6` |
| `accent` | `#EF9F1A` |
| `bg` | `#FFFFFF` |
| `surface` | `#FFFFFF` |
| `text` | `#241F1C` |
| `muted` | `#7A736C` |
| `border` | `#E9E6DF` |

`bg` and `surface` are both white; separate cards from the page with `border`, not a fill.

## 4. Premium palette — Berry Deli (paid health tier)

| Role | Hex |
|------|-----|
| `primary` | `#9E2B4E` |
| `primary-contrast` | `#FFFFFF` |
| `deal` | `#9E2B4E` |
| `save` | `#3E6B4F` |
| `save-soft` | `#E7EFE9` |
| `accent` | `#C6852F` |
| `bg` | `#F7EDE9` |
| `surface` | `#FFFFFF` |
| `text` | `#2E1F26` |
| `muted` | `#7C6A70` |
| `border` | `#EBD9D3` |

Here `bg` (blush) and `surface` (white) differ, so premium cards lift off the
background on their own.

---

## 5. Shared shape & elevation (both tiers)

```css
--radius-sm: 6px;    /* chips, badges */
--radius-md: 10px;   /* cards, inputs, buttons */
--radius-lg: 16px;   /* modals, sheets */
--radius-pill: 999px;/* save pill */

--shadow-card: 0 1px 2px rgba(0,0,0,.04), 0 10px 28px -18px rgba(0,0,0,.20);
--shadow-raised: 0 2px 4px rgba(0,0,0,.06), 0 18px 40px -22px rgba(0,0,0,.28);
```

Spacing: 4px base scale (4 / 8 / 12 / 16 / 20 / 24 / 32 / 48). Card padding 20px.

---

## 6. Implementation

### 6a. CSS custom properties (recommended)

```css
:root {
  /* type */
  --font-heading: "Bricolage Grotesque", system-ui, sans-serif;
  --font-body: "Inter", system-ui, sans-serif;

  /* shape */
  --radius-sm: 6px; --radius-md: 10px; --radius-lg: 16px; --radius-pill: 999px;
  --shadow-card: 0 1px 2px rgba(0,0,0,.04), 0 10px 28px -18px rgba(0,0,0,.20);

  /* color — Standard (Grocery Market) */
  --color-primary: #D8382A;
  --color-primary-contrast: #FFFFFF;
  --color-deal: #D8382A;
  --color-save: #5C7A3A;
  --color-save-soft: #EEF2E6;
  --color-accent: #EF9F1A;
  --color-bg: #FFFFFF;
  --color-surface: #FFFFFF;
  --color-text: #241F1C;
  --color-muted: #7A736C;
  --color-border: #E9E6DF;
}

/* Premium (Berry Deli) — only colors change */
[data-tier="premium"] {
  --color-primary: #9E2B4E;
  --color-primary-contrast: #FFFFFF;
  --color-deal: #9E2B4E;
  --color-save: #3E6B4F;
  --color-save-soft: #E7EFE9;
  --color-accent: #C6852F;
  --color-bg: #F7EDE9;
  --color-surface: #FFFFFF;
  --color-text: #2E1F26;
  --color-muted: #7C6A70;
  --color-border: #EBD9D3;
}
```

### 6b. Tailwind (if the app uses it)

```js
// tailwind.config.js — reads the CSS variables above, so the data-tier swap
// works at runtime with no rebuild.
export default {
  theme: {
    extend: {
      fontFamily: {
        heading: ['"Bricolage Grotesque"', 'system-ui', 'sans-serif'],
        body: ['Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        primary: 'var(--color-primary)',
        'primary-contrast': 'var(--color-primary-contrast)',
        deal: 'var(--color-deal)',
        save: 'var(--color-save)',
        'save-soft': 'var(--color-save-soft)',
        accent: 'var(--color-accent)',
        bg: 'var(--color-bg)',
        surface: 'var(--color-surface)',
        ink: 'var(--color-text)',
        muted: 'var(--color-muted)',
        border: 'var(--color-border)',
      },
      borderRadius: { sm: '6px', md: '10px', lg: '16px', pill: '999px' },
    },
  },
};
```

---

## 7. Component mapping

| Component | Tokens |
|-----------|--------|
| Primary button | bg `primary`, text `primary-contrast`, radius `md`, weight 600 |
| Deal badge | bg `deal`, text white, radius `sm` |
| Save pill | bg `save-soft`, text `save`, radius `pill` |
| Ingredient chip | bg `save-soft` (or `border` tint), text `text`, radius `pill` |
| Card | bg `surface`, border `border`, radius `md`, shadow `--shadow-card` |
| Body text | `text`; captions/meta `muted` |
| Links | `primary` |

---

## 8. Accessibility notes

Contrast checked against WCAG 2.1 AA (4.5:1 normal text, 3:1 large/UI).

- White on Standard `primary` `#D8382A` ≈ **4.6:1** — passes for button labels.
- White on Premium `primary` `#9E2B4E` ≈ **7.2:1** — strong.
- `text` on its `bg` (both tiers) is ~13:1+ — fine.
- `muted` on Standard `bg` ≈ **4.7:1** — passes.
- `muted` on Premium `bg` ≈ **4.4:1** — marginal. If premium `muted` is used for small,
  important text, darken it to about `#6F5E64` (~5:1). Fine as-is for captions.
- **Never put white (or any light) text on `accent`** (`#EF9F1A` / `#C6852F`). Use accent
  as a fill or with `text`-dark on top only.
- Provide a visible keyboard focus ring on all interactive elements
  (e.g. `outline: 3px solid color-mix(in srgb, var(--color-primary) 45%, #fff)`).
