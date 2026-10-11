# Showcase lab

Sign in, open **Showcase lab** in the navigation, and create a showcase workspace.
The workspace starts empty and belongs only to its creator until an administrator
invites another account. Existing bank workspaces keep their portfolios and
membership unchanged. Use the workspace selector to return to a bank workspace.

Choose a scenario, seed, history length, number of cases, and monthly revenue
scale in UZS, then generate cases. **Mixed** produces stable, seasonal, growing,
declining, volatile, and short-history examples. The short-history scenario has
at most four months. Other scenarios use the selected history length. Generated
transactions end in the selected completed calendar month; the default is the
previous completed UTC month. Future or incomplete months are rejected.

Generation creates inputs, not predictions. Open a case and run the normal
assessment workflow against the configured ML service. Inspect the calculated
forecast, capacity score and warnings, then record a human review. The original
model response and each attempt and decision are persisted and audited. An
unavailable scorer or unsupported history produces the normal recorded failure;
the lab does not substitute a score. The teammate model requires at least six
complete months, so short-history examples deliberately exercise its refusal.

The workspace banner and case provenance label these histories as **synthetic**.
They illustrate software behavior, including unfavorable or insufficient inputs;
their names and transactions do not represent actual businesses. Monetary amounts
are generated UZS amounts, not converted legacy indices. For this declared unit,
the unchanged ML `amount_index` transport maps one-to-one to UZS.

The generator is versioned as `showcase-v1`. Each case retains its seed, scenario,
history length, end month, revenue scale and batch position. Repeating those
parameters on the same generator version reproduces the transaction history;
each run creates separate case IDs and a separate audit trail. This provenance
survives application restarts and database backups.

Download generated histories as JSON or CSV from the lab or case workspace.
Exports retain synthetic provenance. Generated CSV uses additional provenance
columns and is intentionally rejected by the bank transaction importer; generated
JSON is rejected there too. Removing provenance and presenting generated amounts
as actual observations would invalidate the data declaration. These exports are
for testing and showcases.

Authenticated generation requires a showcase tenant, a trusted application
origin, a current CSRF token, and access to that tenant. Ordinary registration and
workspace creation always produce empty bank workspaces. The generator cannot
write into a bank portfolio, and actual business imports cannot write into a
showcase workspace. Both administrators and officers can generate and assess lab
cases; administrators control invitations as usual. Tenant checks also protect
case, assessment, decision and audit access.

To keep generation bounded, each request accepts one to six cases, three to 36
months, a seed from 0 to 4,294,967,295, and a revenue scale from 1,000,000 to
1,000,000,000 UZS. A showcase workspace holds at most 100 active cases. The batch
and its audit records commit together; a rejected request leaves the portfolio
unchanged. No accounts or cases are automatically seeded at startup, and the
legacy synthetic archive migration preserves explicitly generated lab cases.

Lab inputs never enter model training automatically. The deployed model artifacts,
frozen evaluations and published model comparison remain unchanged. A successful
showcase verifies the application flow; it does not establish forecast accuracy,
real repayment performance, or default probability. Every final decision still
requires a human.
