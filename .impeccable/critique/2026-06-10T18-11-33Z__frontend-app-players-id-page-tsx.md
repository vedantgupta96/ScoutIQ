---
target: frontend/app/players/[id]/page.tsx
total_score: 28
p0_count: 0
p1_count: 2
timestamp: 2026-06-10T18-11-33Z
slug: frontend-app-players-id-page-tsx
---
#### Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Main data loads cleanly, but page-level loading is a plain text state and rationale generation lacks pre-click cost/status clarity. |
| 2 | Match System / Real World | 4 | Strong NBA front-office vocabulary: cap %, extension window, comps, model interval, and value/pay spread are presented in domain-native terms. |
| 3 | User Control and Freedom | 3 | Back link, tabs, and action rail are useful; duplicated actions create extra decision noise and generation actions are not clearly framed as commands. |
| 4 | Consistency and Standards | 3 | Surface language is coherent, but tabs lack ARIA tab semantics and the app produces two visible h1 landmarks on the player page. |
| 5 | Error Prevention | 2 | Rationale buttons can trigger live billed generation while looking like mode tabs. |
| 6 | Recognition Rather Than Recall | 3 | Executive read is strong; mobile hides later workspace tabs behind horizontal scroll with weak affordance. |
| 7 | Flexibility and Efficiency | 3 | Power users get sticky actions, tabs, and search, but there are no visible keyboard accelerators or command shortcuts. |
| 8 | Aesthetic and Minimalist Design | 3 | Distinctive telemetry-board aesthetic works; first viewport still repeats primary actions across hero and rail. |
| 9 | Error Recovery | 2 | Player errors and API failures are surfaced, but recovery paths and error hierarchy are basic. |
| 10 | Help and Documentation | 2 | Caveats and confidence notes help, but model/rationale limitations are not consistently placed before high-stakes actions. |
| **Total** | | **28/40** | **Strong foundation with focused polish needed** |

#### Anti-Patterns Verdict

**LLM assessment**: This does not read as generic AI slop. The page has a specific product identity: clipped decision surfaces, team-tinted case visuals, cap-space gauges, tabular numerics, and a cockpit composition that fits NBA front-office work. The main slop risk is not aesthetic blandness; it is product-density drift. The hero, workspace tabs, action rail, and three-panel brief all compete for first-viewport priority.

**Deterministic scan**: `detect.mjs --json frontend/app/players/[id]/page.tsx` returned `[]`. No bundled slop or technical UI-pattern findings were reported for the target file.

**Visual overlays**: Browser overlay injection was not used because the Codex Browser skill was not available in this session. Fallback browser evidence used Playwright screenshots at desktop and mobile viewports after escalation. Desktop screenshot: `/tmp/scoutiq-player-critique-desktop.png`. Mobile screenshot: `/tmp/scoutiq-player-critique-mobile.png`.

#### Overall Impression

ScoutIQ's player page is already meaningfully differentiated. It feels like a decision workspace, not a template dashboard. The biggest opportunity is to sharpen the task model: make the top-level decision, tabs, and next actions feel less redundant and make high-stakes/generative actions unmistakably intentional.

#### What's Working

- The decision hero makes the value case immediately visible: player, team, model value, current pay, extension window, verdict, and actions are all present before the data inventory.
- The value/pay gauge is the signature element. It turns uncertainty and overpay/surplus into a physical read, which matches the design system's "contract math has shape" principle.
- The `Surface` variants create a strong product language. Instrument, board, and dossier surfaces map well to model readouts, market comps, and scouting/source notes.

#### Priority Issues

**[P1] Generative rationale actions look like tabs instead of costly commands**  
**Why it matters**: The code comment says generation is live and billed, but the UI presents "Model vs scout" and "Multi-source" as mode tabs. A user can click them expecting a local view switch and trigger an external generation flow.  
**Fix**: Rename the controls to command verbs, such as "Generate model vs scout" and "Generate multi-source rationale." Add one compact pre-click line that says generation may call external providers and cached results will show cost after completion. Add `aria-busy` during generation.  
**Suggested command**: `$impeccable clarify`

**[P1] Mobile workspace tabs hide core sections with weak affordance**  
**Why it matters**: At 390px, the first viewport shows Front-office read, Similar market, and a clipped Contract icon; Scout and Model are off-screen. Those are core trust-building sections, especially for analysts and scouts.  
**Fix**: On narrow mobile, wrap the tab control into a compact two-column grid or add a visible edge fade/scroll hint. The simpler robust fix is wrapping into visible rows.  
**Suggested command**: `$impeccable adapt`

**[P2] Accessibility semantics are close but incomplete**  
**Why it matters**: The page currently has the Shell title h1 plus the player name h1, workspace tabs are plain buttons without tab semantics, and topbar icon buttons include controls with no accessible names. This weakens keyboard and screen-reader confidence in a dense product surface.  
**Fix**: Make the Shell title non-h1 chrome, give workspace tabs `tablist`/`tab`/`aria-selected`, add labels for theme/notification/clear-search controls, and avoid nested `main` landmarks inside the app shell.  
**Suggested command**: `$impeccable audit`

**[P2] First viewport repeats actions across hero and rail**  
**Why it matters**: "Run simulation"/"Simulate extension" and pricing actions appear both in the hero and action rail. Repetition can be useful when sticky, but here it makes the decision page feel busier than necessary before the user has chosen a direction.  
**Fix**: Keep the hero as the decisive next step. Let the action rail become "Case file" plus secondary navigation, or make the rail's actions visually quieter until the user scrolls past the hero.  
**Suggested command**: `$impeccable layout`

**[P3] Loading and error states do not yet match the cockpit language**  
**Why it matters**: The main page uses a plain centered "Loading..." state and a simple negative block for player errors. These are functional, but they do not preserve the credibility of the rest of the page when the API is slow or unavailable.  
**Fix**: Use an instrument-style loading skeleton for the hero and a dossier-style error state with retry/back actions.  
**Suggested command**: `$impeccable harden`

#### Persona Red Flags

**Alex (Power User)**: The action rail helps fast movement, but repeated hero/rail actions add scan noise. No keyboard shortcut or command palette path is visible for jumping between Model, Contract, and Market.

**Morgan (Cap Strategist)**: The cap/value read is strong, but "Generate" actions need clearer cost and external-call framing. Morgan will want to know whether a click changes state locally, calls a provider, or spends budget.

**Jordan (First-Timer)**: The first mobile view hides Scout and Model tabs. Jordan may not discover the trust-building sections that explain why the recommendation is credible.

#### Minor Observations

- Desktop rendered cleanly at 1440x900 with no console errors, no failed requests, and no horizontal document overflow.
- Mobile rendered cleanly at 390x900 with no console errors and no document-level horizontal overflow.
- The main scroll container is internal, so document `scrollHeight` is not a reliable page-depth measure.
- Abbreviations like V/P/G in similar-player rows are dense; acceptable for power users, but they need tooltips or clearer labels if exposed broadly.

#### Questions to Consider

- Should the action rail be a sticky command center, or should it become a passive case-file summary until the user scrolls?
- Should generative rationale be treated as a premium action with explicit confirmation, or as a lightweight cached helper?
- On mobile, is fast tab switching more important than preserving vertical density in the first viewport?
