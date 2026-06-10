---
name: ScoutIQ
description: "NBA front-office decision cockpit for player value, contract risk, and cap pressure."
colors:
  accent-orange: "#FF5A1F"
  accent-orange-hover: "#D64A16"
  accent-orange-press: "#A9370F"
  confidence-teal: "#0E9C9C"
  positive-green: "#15945A"
  negative-red: "#CB2C2C"
  warning-amber: "#C68A12"
  info-blue: "#2F6FE0"
  light-app: "#F0F2F0"
  light-backdrop: "#E2E6E4"
  light-panel: "#FBFCFA"
  light-elevated: "#FFFFFF"
  light-inset: "#E9ECEA"
  light-ink: "#0E1116"
  light-secondary: "#4B5563"
  light-muted: "#79828F"
  dark-app: "#080A08"
  dark-backdrop: "#050605"
  dark-panel: "#111510"
  dark-elevated: "#171C16"
  dark-inset: "#0D100D"
  dark-ink: "#F4F6EE"
  dark-secondary: "#C5CCBC"
  dark-muted: "#9DA691"
typography:
  display:
    fontFamily: "Saira Semi Condensed, system-ui, sans-serif"
    fontSize: "32px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Saira Semi Condensed, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.2
  title:
    fontFamily: "Commissioner, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 700
    lineHeight: 1.35
  body:
    fontFamily: "Commissioner, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  data:
    fontFamily: "Azeret Mono, ui-monospace, monospace"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.015em"
rounded:
  xs: "3px"
  sm: "5px"
  md: "7px"
  lg: "10px"
  xl: "14px"
  pill: "999px"
spacing:
  1: "4px"
  2: "8px"
  3: "12px"
  4: "16px"
  5: "20px"
  6: "24px"
  8: "32px"
  12: "48px"
components:
  button-primary:
    backgroundColor: "{colors.accent-orange}"
    textColor: "#FFFFFF"
    rounded: "{rounded.md}"
    padding: "9px 16px"
  button-primary-hover:
    backgroundColor: "{colors.accent-orange-hover}"
    textColor: "#FFFFFF"
    rounded: "{rounded.md}"
    padding: "9px 16px"
  button-secondary:
    backgroundColor: "{colors.light-panel}"
    textColor: "{colors.light-secondary}"
    rounded: "{rounded.md}"
    padding: "8px 12px"
  surface-panel:
    backgroundColor: "{colors.light-panel}"
    textColor: "{colors.light-ink}"
    rounded: "{rounded.lg}"
    padding: "12px 16px 16px"
  badge:
    backgroundColor: "{colors.light-inset}"
    textColor: "{colors.light-secondary}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
---

# Design System: ScoutIQ

## 1. Overview

**Creative North Star: "The Front-Office Telemetry Board"**

ScoutIQ is a decision cockpit for NBA executives, cap strategists, analysts, and scouts. The interface should feel precise, cinematic, and intellectually aggressive: an evidence room where valuation, scouting context, and cap pressure converge into one decision state.

The system is product UI, not a campaign. Familiar controls are allowed, but their material language is specific: clipped dossier corners, instrument panels, team-tinted rails, tabular numerics, cap-pressure bands, and quiet court geometry. The memorable element is not ornament; it is the way uncertainty, pay/value spread, and roster consequence are given a physical shape.

**Key Characteristics:**
- Dense, scan-first layouts with the decision state visible before the data inventory.
- Restrained chrome, sharp state color, and vivid data treatments only where they clarify risk, confidence, or value.
- Basketball-native structure: court marks, ledgers, gauges, plates, brackets, and dossiers instead of generic dashboard cards.
- Light and dark themes share one vocabulary; dark is a war-room mode, light is an analysis desk.

## 2. Colors

The palette is a restrained tactical neutral system with orange as the decision accent and teal as the confidence signal. Green, red, amber, and blue are reserved for semantic data states.

### Primary
- **Shot Clock Orange** (#FF5A1F): Primary action, current selection, active nav, focus ring, and decisive recommendation emphasis. Use sparingly; its rarity creates authority.
- **Press Orange** (#A9370F): Active/pressed action state and deeper warning pressure.

### Secondary
- **Confidence Teal** (#0E9C9C): Model confidence, uncertainty bands, source credibility, and instrument accents. Do not use it as generic decoration.

### Tertiary
- **Value Green** (#15945A): Surplus value and favorable outcomes.
- **Overpay Red** (#CB2C2C): Negative spread, risk, and unfavorable outcomes.
- **Apron Amber** (#C68A12): Caution, threshold proximity, and assumptions that need review.
- **Trace Blue** (#2F6FE0): Informational metadata, links, and neutral evidence routes.

### Neutral
- **Film Room Light** (#F0F2F0): Light app background. Slightly cool and green-tinted; never cream, parchment, or beige.
- **Light Panel** (#FBFCFA): Main content panel surface.
- **Light Inset** (#E9ECEA): Wells, controls, and recessed data areas.
- **Light Ink** (#0E1116): Primary text.
- **Light Muted** (#79828F): Secondary labels and support text.
- **War Room Dark** (#080A08): Dark app background.
- **Dark Panel** (#111510): Dark primary surface.
- **Dark Inset** (#0D100D): Dark recessed control surface.
- **Dark Ink** (#F4F6EE): Dark-mode primary text.

### Named Rules

**The State Color Rule.** Orange means action or selection, teal means confidence, green/red means value spread, amber means threshold caution, and blue means informational traceability. Do not blur these meanings.

**The No Sports Palette Rule.** Never default to navy-and-gold, betting-board neon, or fan-site team collage. Team colors may tint player/team surfaces, but ScoutIQ owns the chrome.

## 3. Typography

**Display Font:** Saira Semi Condensed, with system sans fallback  
**Body Font:** Commissioner, with system sans fallback  
**Label/Mono Font:** Azeret Mono, with monospace fallback

**Character:** Saira gives headings and major numeric readouts a condensed scouting-report authority. Commissioner keeps dense product UI legible. Azeret Mono is used for money, percentages, deltas, ticks, and model values that need tabular alignment.

### Hierarchy
- **Display** (700, 32px, 1.0 line-height): Player names, major decision headers, and large stat readouts. Keep letter spacing no tighter than -0.02em.
- **Headline** (600, 20px, 1.2 line-height): Top bar titles and compact page-level headings.
- **Title** (700, 14px, 1.35 line-height): Panel labels, row group titles, and dense component headings.
- **Body** (400-500, 14px, 1.5 line-height): Interface copy, rationale, empty states, and explanatory text. Cap prose at 65-75ch when it is not tabular.
- **Label** (600-700, 11-12px, 0.01-0.02em): Badges, compact labels, and section identifiers. Use sentence case or domain casing, not tiny all-caps scaffolding.
- **Data** (600-700, 13px+, tabular numerics): Percent of cap, salary, model intervals, deltas, and slider values.

### Named Rules

**The Numbers Are Evidence Rule.** Every money value, percent, delta, and model output uses tabular numerics. Decorative display type never appears in buttons, inputs, or dense labels.

## 4. Elevation

ScoutIQ uses a hybrid of tonal layering, clipped geometry, and very tight shadows. Surfaces should feel like instruments and dossiers laid into the cockpit, not floating cards. Depth is mostly conveyed through panel tint, borders, inset wells, and state response; shadows stay short and structural.

### Shadow Vocabulary
- **Card Shadow** (`0 1px 0 rgba(24,31,24,0.07), 0 4px 8px -6px rgba(24,31,24,0.30)`): Default panel lift in light mode.
- **Medium Shadow** (`0 1px 0 rgba(24,31,24,0.10), 0 7px 8px -7px rgba(24,31,24,0.34)`): Hover lift for interactive surfaces.
- **Accent Glow** (`0 0 0 1px rgba(255,90,31,0.28), 0 5px 8px -6px rgba(255,90,31,0.48)`): Primary action emphasis only.
- **Focus Shadow** (`0 0 0 3px rgba(244,98,31,0.25)`): Focus and high-confidence selection reinforcement.

### Named Rules

**The Instrument Depth Rule.** Use a border or a compact shadow, not both as decoration. If a shadow appears, it should mark state, hierarchy, or action priority.

## 5. Components

### Buttons
- **Shape:** Compact rectangular controls with a 7px radius.
- **Primary:** Shot Clock Orange fill, white text, 9px 16px padding, 13px Commissioner semibold, short accent glow.
- **Hover / Focus:** Primary buttons shift to hover orange and move up 1px. Focus uses the global orange outline and never removes keyboard visibility.
- **Secondary:** Panel fill, default border, secondary text, 8px 12px padding. Hover strengthens border and ink.

### Chips
- **Style:** Pill badges with 2px 8px padding, 11-12px Commissioner semibold, and tone-specific soft backgrounds.
- **State:** Dots are allowed when they communicate model/data status. Tone names must match semantic meaning: neutral, accent, positive, negative, warning, confidence.

### Cards / Containers
- **Corner Style:** 10px radius with a clipped top-right corner for cards and surfaces.
- **Background:** Layered panel gradients can include a 5-8% accent wash, but the panel must remain readable.
- **Shadow Strategy:** Default card shadow at rest, medium shadow on hover for interactive panels only.
- **Border:** 1px subtle border by default. Team or surface accents can tint the border up to roughly 20-26%.
- **Internal Padding:** Standard body padding is 12px 16px 16px. Flush bodies are reserved for ledgers, rails, and charts.

### Inputs / Fields
- **Style:** Panel or inset background, 7px radius, 1px subtle border, 13-14px Commissioner.
- **Focus:** Orange focus outline or border shift. Placeholder text must maintain readable contrast.
- **Error / Disabled:** Error uses red text plus explicit copy. Disabled state reduces contrast and cursor affordance without hiding labels.

### Navigation
- **Style:** 232px sidebar, 56px top bar, compact icon+label rows, active state in orange text with a thin underline marker.
- **Collapsed:** 60px icon rail. Labels disappear; icons retain accessible labels.
- **Mobile:** Sidebar remains a compact rail; search and page title adapt without forcing horizontal scroll.

### Signature Component

**Decision Surfaces** are the core ScoutIQ component language. `plain`, `instrument`, `board`, and `dossier` variants should map to content type: flat facts, model readouts, comp/market comparisons, and scouting/source notes. Do not replace these with generic card grids.

## 6. Do's and Don'ts

### Do:
- **Do** make the decision state visible before the full data inventory.
- **Do** use orange for actions/selection and teal for model confidence; preserve those meanings across every screen.
- **Do** give contract math a physical shape through timelines, bands, pressure zones, gauges, ledgers, and consequence markers.
- **Do** use team colors as contextual surface tints, not as the app identity.
- **Do** keep UI controls compact, familiar, and keyboard accessible.
- **Do** respect reduced motion; motion should indicate state changes, loading, or data updates.

### Don't:
- **Don't** use generic SaaS dashboard patterns: stacked white cards, flat gray tables, timid accent colors, identical metric tiles, or motionless admin chrome.
- **Don't** use sports-betting aesthetics, fan-site clutter, overused navy-and-gold sports palettes, fake glassmorphism, or decorative data visuals that do not improve decision-making.
- **Don't** use gradient text, decorative glass cards, side-stripe card accents, or repeated 01/02/03 section scaffolding.
- **Don't** turn labels into tiny uppercase tracked eyebrows across the product.
- **Don't** introduce cream, sand, parchment, or beige body backgrounds; ScoutIQ's light mode is cool film-room neutral.
- **Don't** animate layout properties for routine state changes. Use transform/opacity where motion is useful, or snap structural layout changes.
