# PlanQA Review Agent

# Workflow

## Collaboration

### Code Styles

- Use modern language features
- Limit lines to 120 characters maximum.
- Prefer pure functions where possible.
- NEVER write docstrings, function descriptions, or line-by-line comments.
- Only add inline comments to explain the *why* of non-obvious business logic, not the *what* of the code.

### Commit Template

`<category>: <short_summary>`

- categories: 'feat', 'fix', 'refactor', 'docs', 'test', 'chore', 'perf'
- example: `feat: add validation to prevent crash on special chars`
- **70 chars max**, imperative, English only
- NO body lines, NO co-authoring yourself.

## Progress Log

- Keep a running log of work in `docs/progress.md`.
- One dated section per work session (`## YYYY-MM-DD — short title`), newest at the bottom.
- Each entry: what was done, key results (tables/numbers where relevant), and a `### Next` list of
  what's left. This is the backup of "what Claude did" across sessions — write it so a fresh session
  (or teammate) can pick up context without re-reading the whole diff history.

## Architectural Decision Record (ADR)

- Save all ADRs in the `docs/adr/` folder.
- Use 4-digit numbers so the ADRs stay in order: `docs/adr/NNNN-decision-title.md`

### ADR Template

- Title: A short name (e.g., Use PostgreSQL for Database)
- Status: Draft, Accepted, Rejected, or Deprecated
- Date: Date & time
- Context: What is the problem and what rules limit your choices?
- Options: What other choices did you think about?
- Decision: What is the final choice and why?
- Consequences: The pros, cons, and trade-offs of this choice.
