# ScoutIQ — Explainable NBA Contract Intelligence

> A decision-support cockpit for NBA roster construction. ScoutIQ fuses structured stats,
> unstructured scouting text, and salary-cap math into a single, **explainable** recommendation —
> not "what happened," but "what this player is worth, what a deal does to your cap, and why."

---

## 1. Positioning

- **Sport:** NBA (only league where valuation + a real salary cap + guaranteed contracts + abundant
  public scouting text all coexist).
- **Primary user:** a team front office (GM / capologist / scout). We design the UX *as if* a GM uses
  it — that framing is what makes the feature set cohere into "decision intelligence."
- **Project type:** portfolio piece. Optimized for: a live demo, one undeniable "wow" feature, visible
  rigor, and clean architecture — **not** feature count.
- **Posture on ML:** calibrated and honest. We show uncertainty, backtest our claims, and refuse to
  fake signal we don't have. "Correct on the 80% that matters, explicit about the rest."

### The one-line pitch
> ScoutIQ tells a front office what a player is worth, what a proposed contract does to their cap and
> tax position, and explains the reasoning in plain language — with confidence intervals, not false
> precision.

---

## 2. The Signature Feature (lead every demo with this)

**What-If Contract & Cap Simulator, wired to an explainable valuation engine.**

The user drags sliders for contract length / guaranteed money / incentives and instantly sees:
- Year-by-year **cap hit** and **luxury-tax / apron** impact
- **Team flexibility** (exceptions, room, hard-cap implications)
- **Model value vs. proposed value** (e.g. "~12% above fair value")
- A **natural-language rationale**: *"Comparable to [X]'s extension; pushes you into the second apron in
  Year 3; projected to age out of starter value by Year 4."*

This is the screenshot on the README. Almost no portfolio project combines live cap math with an
explainable valuation model — this is the differentiator.

---

## 3. Rigor Layer (what separates this from demo-ware)

A reviewer in 2026 will poke at "how do you know any of this is right?" Most candidates have no answer.
ScoutIQ has two:

### 3.1 Valuation backtest
- Train on contracts signed 2015–2022, evaluate predicted-vs-actual on 2023–2025.
- Report calibration explicitly (e.g. reliability plot, interval coverage).
- Ship the backtest results *in the UI*, not just a notebook. Showing calibration is the single most
  credible thing in the whole project.

### 3.2 LLM evaluation harness
- A small **gold set** of scouting notes, hand-labeled with the structured ratings we expect.
- Measure the LLM's extraction against it (agreement / rubric scores), and track it as the prompt evolves.
- This is the answer to "is your LLM actually any good?" — have it ready.

---

## 4. Architecture

### Frontend
- Next.js (App Router) + TypeScript
- Tailwind CSS + shadcn/ui
- **Recharts / visx** for most charts (fast to build)
- **D3.js reserved for the ONE signature viz** (the cap/contract timeline) — don't hand-roll the rest
- Framer Motion for polish

### Backend
- FastAPI (Python) — also where deterministic cap/contract math lives (it's cheap; no need to cache it)

### Data
- **PostgreSQL** — system of record: players, teams, contracts, seasons, injuries, scout reports, valuations
- **pgvector** — scout-report embeddings, similar-player search, semantic retrieval
- **Redis** — caching expensive LLM/model calls + Perplexity responses; sessions. *(Not "real-time
  calculations" — cap math is deterministic and belongs in FastAPI.)*
- **Neo4j — deferred to Phase 3, optional.** Postgres recursive CTEs cover relationship queries at this
  data scale. Only add Neo4j if "graph DB" is a resume goal worth the ops cost.

### LLM / AI layer
- Claude (latest, e.g. `claude-opus-4-8` or `claude-sonnet-4-6`) for scouting-text → structured ratings,
  consensus synthesis, and the natural-language rationale generation.
- **Perplexity Sonar API** for the *qualitative* ingestion layer only (see §5).
- An **eval/observability** path so LLM output quality is measurable, not vibes.

---

## 5. Data Pipeline (this is where the project lives or dies)

> The ML is learnable; the **ETL is the real work**. Budget accordingly.

| Layer | Source | Notes |
|-------|--------|-------|
| Stats (numbers) | `nba_api`, Basketball Reference | Deterministic, clean. The backbone. |
| Contracts / cap (numbers) | Spotrac / Basketball-Insiders ETL | Messy, ToS-gray scraping. **Hardest part.** Budget real time here. |
| Scouting / news (text) | Perplexity Sonar, articles, draft writeups, Reddit | Qualitative context + citations for RAG. |

### Rule of thumb
- **Numbers → deterministic, verifiable ETL.** Never an LLM. Reproducibility is part of the rigor story.
- **Words → Perplexity Sonar / Claude.** Search-grounded text with citations.

### Perplexity Sonar usage (the right way)
- Use it to pull **recent scouting narratives, injury news, and trade buzz** per player, *with citations
  stored alongside*.
- **Cache every response in Redis**, keyed by `query + date`. Sonar is non-deterministic and metered —
  never call it in the request path.
- Feeds the scouting-synthesis and RAG features. Do **not** use it to fetch stats, salaries, or cap
  numbers (hallucination risk, no reproducibility).

### Salary-cap modeling
- The real CBA is complex (Bird rights, mid-level/bi-annual exceptions, two aprons since 2023). **Do not
  model all of it.**
- Implement a **simplified-but-correct subset**, and **state assumptions in the UI**. Correct on the
  decisions that matter, honest about the edges.

---

## 6. ML Features (calibrated & honest)

### 6.1 Contract Valuation Engine — *the flagship model*
- **Predict:** fair market value + **confidence interval** + recommended structure.
- Backtested (§3.1). Lead with calibration, not point accuracy.
- Features: production metrics, age curve, position, role, availability, market context (cap inflation).

### 6.2 Performance Forecasting — *uncertainty-aware*
- **1–2 year horizon only.** Output **uncertainty bands**, not point estimates.
- **The 5-year point projection is cut** — variance from injuries/role/team-fit makes it indefensible.

### 6.3 Injury Indicator — *transparent, not a "prediction"*
- Reframed honestly: a **risk indicator** from age, minutes/workload, and injury history — the only signal
  public data actually carries.
- We **do not** claim to predict injuries; real models need biometric/GPS/load data teams don't release.
  Stating this *is* the credibility move.

---

## 7. LLM Features

### 7.1 Scout Report Analysis
Convert unstructured scouting notes into structured ratings (leadership, coachability, work ethic,
athleticism, discipline, basketball IQ). Validated against the gold set (§3.2).

### 7.2 Multi-Scout Consensus
Combine multiple scouting opinions into a unified recommendation, surfacing where scouts disagree (the
disagreement is often the interesting part).

### 7.3 Rationale Generation
Generate the plain-language "why" behind every valuation and cap recommendation — grounded in the
model's actual inputs (no free-floating prose).

---

## 8. Knowledge Graph (Phase 3, optional)

Default implementation in **Postgres (recursive CTEs)**; promote to Neo4j only if desired.

- **Nodes:** Player, Team, Agent, Coach, Contract, Injury, Scout
- **Edges:** Played For, Represented By, Coached By, Similar To, Recommended By
- Use cases: agent-network analysis, comparable-player chains, scout-recommendation provenance.

---

## 9. Roadmap

### Phase 1 — *the deliverable* (a complete project on its own)
- NBA player + contract database
- ETL pipeline (stats + contracts)
- **Contract valuation engine + confidence intervals + backtest**
- **What-If Cap Simulator** (signature feature)
- Front-office dashboard
> Test of good scoping: if you ship only Phase 1, you still have a strong portfolio piece.

### Phase 2 — *the AI story*
- Scouting-text → structured ratings (Claude) + **LLM eval harness**
- Perplexity Sonar qualitative ingestion (cached, cited)
- Similar-player search (pgvector)
- Multi-scout consensus + rationale generation

### Phase 3 — *stretch*
- Uncertainty-aware forecasting
- Injury indicator
- Relationship graph (Postgres CTEs → optional Neo4j)
- Monte Carlo contract/cap scenarios

---

## 10. Why This Project Is Unique

Most sports tools explain *what happened*. ScoutIQ does three things almost none of them combine:

1. **Live cap math + explainable valuation** in one interface (the signature feature).
2. **Fusion of structured stats + unstructured scouting text + contract math** into one recommendation.
3. **Calibrated honesty** — confidence intervals, a published backtest, an LLM eval harness, and an
   explicit refusal to fake signal that public data can't support.

Demonstrated skills: full-stack engineering, data engineering / ETL, applied ML with proper evaluation,
LLM application design + evals, search-grounded retrieval (RAG), and decision-intelligence UX.

> ScoutIQ doesn't just predict — it explains, quantifies its uncertainty, and helps a front office make a
> better decision.
