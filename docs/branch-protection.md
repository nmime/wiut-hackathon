# Branch protection recommendation

If repository settings are not managed automatically, protect `main` with:

- pull requests required before merge;
- `pnpm check`, CodeQL, and relevant deployment checks required;
- stale approvals dismissed after new commits;
- conversation resolution required;
- force pushes and branch deletion disabled;
- signed commits/tags if your organization requires them.

Use squash merges for boilerplate-sized feature branches unless release history requires merge commits.

## Branch and commit convention

Human topic branches use `<type>/<kebab-case>`. Allowed types are `feat`,
`fix`, `docs`, `chore`, `refactor`, `test`, `ci`, `perf`, `build`, `revert`,
`release`, and `hotfix`. `main` is the protected branch, and
`dependabot/**` is the only generated-name exception. Branch path segments must
never identify an assistant or vendor, including `codex` and `claude`.

Commits use `<type>(<optional-scope>)!: <lowercase description>` with
Conventional Commit types `feat`, `fix`, `docs`, `chore`, `refactor`, `test`,
`ci`, `perf`, `build`, or `revert`. Keep history linear; squash or rebase topic
branches instead of adding merge commits. Every author and committer must be
the real contributor. Commits produced by repository agents instead use
exactly `nmime <66474195+nmime@users.noreply.github.com>` as both author and
committer, with no assistant attribution trailers. Human contributor and
trusted dependency-bot identities remain valid.

Run `pnpm run git:conventions`; CI applies it to the complete PR or push range.

## Branch cleanup safety

Use `pnpm run branch:cleanup:check` before deleting stale branches. The check mode prints JSON with the merged local candidates for `HEAD` (the `branch:cleanup:check` script passes `--target HEAD`; the plain `branch:cleanup` command uses the `origin/main` default) and does not mutate refs. To delete local merged branches, run `pnpm run branch:cleanup -- --apply`. Remote cleanup is opt-in and requires both `--remote` and `--apply`, which prevents accidental deletion during CI, audits, or dry runs.

The cleanup guard never proposes protected refs: `main`, `master`, `develop`, `development`, `release/*`, `hotfix/*`, `prod`, `production`, `staging`, or `origin/HEAD`. Keep remote branch cleanup disabled in CI unless a repository maintainer is executing a reviewed maintenance workflow.
