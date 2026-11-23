# Superlion website design

Taken from the app icon (a traction engine's crimson, brass and black livery) and from the app
itself, which is libadwaita in dark mode. The page should feel like the app: calm, dark, and
let the screenshots carry it.

## Colour

| Token | Light | Dark | Role |
|---|---|---|---|
| `--bg` | `#faf8f5` | `#16130f` | Page background |
| `--surface` | `#ffffff` | `#211d18` | Raised areas: install box, code |
| `--text` | `#1d1a16` | `#f3efe8` | Body text and headings |
| `--muted` | `#5f574c` | `#b5aca0` | Secondary text |
| `--border` | `#e4ded4` | `#352f27` | Rules and outlines |
| `--primary` | `#a62233` | `#e0566a` | Buttons and links |
| `--on-primary` | `#ffffff` | `#16130f` | Text on primary buttons |
| `--brass` | `#8f620c` | `#d9a33a` | The one accent: eyebrows, rules beside headings |
| `--ring` | `#000000` | `#ffffff` | Ring around the dedication photo |

All text pairs reach 4.5:1 or better. No gradients.

## Typography

- Headings: Fraunces (Google Fonts), weight 600, optical size on.
- Body: Inter, weights 400 and 600.
- Code: ui-monospace stack.
- Scale (rem / line height): 3.25/1.05, 2.25/1.15, 1.5/1.25, 1.125/1.5, 1/1.6, 0.875/1.5.
- Body text 1rem minimum; text blocks at most 62ch.

## Spacing and layout

- 8px scale: 4, 8, 12, 16, 24, 32, 48, 64, 96.
- Sections 96px apart on desktop, 64px on phones.
- Content width 1120px; 16px side gutter on phones.

## Shape

- Radius: 8px for buttons and code, 12px for screenshots, which keep the app's window shape.
- One shadow, for screenshots only: `0 24px 48px -16px rgb(0 0 0 / 0.45)`.

## Components

- Primary button: `--primary` fill, `--on-primary` text. Secondary: outline in `--border`.
  Both show a 2px `--brass` focus ring with a 2px offset.
- Links: `--primary`; underlined in running text, and on hover elsewhere.
- Code blocks: `--surface`, with a Copy button.
- Feature rows alternate the screenshot side on desktop and stack on phones.

## Imagery

Real screenshots from `screenshots/` only. The app icon in the header. No stock photos,
illustrations or emoji.
