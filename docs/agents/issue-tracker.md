# Issue tracker: Linear

ScoutIQ work is tracked in the [ScoutIQ Linear project](https://linear.app/vedantspersonalprojects/project/scoutiq-cae8feb57aed), on the `ScoutIQ` team (`SCO`). Linear is the source of truth; GitHub is the review surface.

## Card lifecycle

| State | Meaning |
|---|---|
| Backlog | Not ready, or blocked |
| Todo | Ready to pick up |
| In Progress | Agent claimed, draft PR, or changes requested |
| In Review | Non-draft PR is ready for review |
| Done | Whole card accepted and its closing PR merged to `main` |

Native Linear automation is configured as Draft → In Progress; PR open, review activity, and ready-to-merge → In Review; merge → Done. Auto-close stale issues is disabled. Changes requested or a closed unmerged PR are reconciled manually to In Progress or Todo. Do not infer Done from a count of merged partial PRs.

## Picking up the next card

When asked to “pick up the next card”, use connected Linear tools and inspect every page of `SCO` cards. Before selecting or resuming, reconcile every started leaf card against its linked live PRs:

- Draft-only work is In Progress. An open ready PR is In Review unless changes were requested, which is In Progress.
- If all PRs are closed unmerged, or all contributing `Part of` PRs are merged while scope remains, move an unclaimed card to Todo when the remaining bounded acceptance criteria are ready; otherwise move it to Backlog and comment with the exact gate.
- A closing PR merged to `main` becomes Done only when the whole card is accepted and every linked closure PR is complete. Native automation owns the normal transition; if it is stale, reconcile it and record the evidence.
- Never auto-complete maps or cards with remaining acceptance criteria.

Then resume only your own genuinely actionable bounded leaf: In Progress work, a draft PR, changes requested, or unmerged local work. Do not resume a ready PR solely because it awaits external review; note its status and choose the next eligible card in a clean isolated worktree if needed. Do not take another agent's claim, resume a merged branch merely because its name contains an `SCO-N`, or resume a roadmap or umbrella card. Otherwise consider only cards that:

- are `Todo`, labelled `ready-for-agent`, and have priority 1–4;
- have no unresolved native `blocked by` relation;
- are not `wayfinder:map`, `ready-for-human`, `needs-info`, `needs-triage`, or `wontfix`;
- have no open PR, existing claim, or active review; and
- are not gated on a human or an unavailable source.

Before ranking, inspect Backlog cards already labelled `ready-for-agent`. Promote one to Todo only when every native blocker is Done, its acceptance criteria remain specific, and it has no human/source gate, open PR, or claim. Never promote `needs-triage`, `needs-info`, or `ready-for-human` merely because a blocker closed. Then sort eligible cards by priority ascending, then by the number of active cards they block descending, then by numeric `SCO-N` ascending. Do not claim an umbrella card when a bounded child is the executable unit.

Immediately before a claim, re-read the card to avoid an obvious race. There is no guaranteed atomic lock: do not start a card another agent has claimed. Set the card to In Progress, keep the assignee as Vedant Gupta (or assign the connected user, `me`), and add a short comment with the branch, card, and scope before changing code. Do not assign a Codex or Claude agent identity. Follow the repository model split: the main thread plans and reviews; exactly one implementer makes code changes.

If blocked, comment with the exact missing need, remove `ready-for-agent`, add `needs-info` or `ready-for-human`, and move the card to Backlog. Then choose the next eligible card.

## PR links and closure

Use one closing card per PR and put its `SCO-N` in the title.

- `Fixes SCO-N` only when the PR completes the whole accepted card.
- `Part of SCO-N` for a partial PR.
- `Relates to SCO-N` for an umbrella card; create a bounded, prioritized, ready-labelled child for executable work.

The merge-to-Done automation is valid only when the PR targets `main`, has one whole accepted card, and uses its matching `Fixes SCO-N` reference. Stacked PRs must use `Part of SCO-N`; the metadata contract check rejects or flags an invalid stacked closure once it runs, until branch protection requires it. Deployment verification is either an explicit follow-up or an acceptance gate. Never auto-merge, retrain, deploy, or spend on a paid service without authorization; routine implementation choices do not need separate approval.

## Triage and native automation runbook

The native intake template applies to members and nonmembers: project ScoutIQ, assignee Vedant Gupta, priority Medium (3), Backlog, and `needs-triage`. Every issue has a nonzero priority: Urgent (1) is incidents only; High (2) is integrity, reliability, or blockers; Medium (3) is normal work; Low (4) is polish or future work. Periodically correct stale Done cards, missing priority, and cards that no longer meet their labels.

Main-thread workspace setup uses native Linear/GitHub integration only: Draft → In Progress; PR open/review/ready → In Review; merge → Done. SCO-50 PR 158 verified the draft and ready/In Review transitions; merged-`main` verification remains pending. The repository metadata check is not status sync and needs no Linear credential; it first runs only after its workflow reaches the default branch. Do not add custom sync code or secrets.

## Conventions

- Create, read, list, comment, label, and relate work with connected Linear tools or the Linear UI.
- Include the relevant `SCO-N` in agent prompts, branches, and pull requests.
- A Wayfinder map is a parent issue labelled `wayfinder:map`; its bounded children use `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or `wayfinder:task` and native blocking relations.
