# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues in `vedantgupta96/ScoutIQ`. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body-file <file>`
- **Read an issue**: `gh issue view <number> --comments`
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments`
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply or remove labels**: `gh issue edit <number> --add-label "..."` or `--remove-label "..."`
- **Close an issue**: `gh issue close <number> --comment "..."`

Infer the repository from `git remote -v`; `gh` does this automatically inside the clone.

## Pull requests as a triage surface

**PRs as a request surface: no.**

GitHub pull requests are not included in the issue-triage queue.

## When a skill says “publish to the issue tracker”

Create a GitHub issue.

## When a skill says “fetch the relevant ticket”

Run `gh issue view <number> --comments`.

## Wayfinding operations

The map is a single issue with child issues as tickets.

- **Map**: an issue labelled `wayfinder:map`, containing Notes, Decisions-so-far, and Fog.
- **Child ticket**: a GitHub sub-issue linked to the map. If sub-issues are unavailable, add it to the map’s task list and include `Part of #<map>` in the child.
- **Child labels**: `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or `wayfinder:task`.
- **Blocking**: use GitHub native issue dependencies. If unavailable, add `Blocked by: #<number>` to the child.
- **Claim**: `gh issue edit <number> --add-assignee @me`.
- **Resolve**: comment with the answer, close the child, and update the map’s Decisions-so-far section.
