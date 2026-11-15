## Proposal

### What

Free-form operator labels on catalog subjects (file seed / post / asset / work):
create and retire labels at will, apply and revoke them on any subject, search
subjects by label, and treat a label as covering identical content regardless of
platform.

### Why

Everything tag-shaped in the catalog is provider-observed; there is deliberately
no way to record a local fact ("ai-generated", "needs-review", "kemono batch").
The operator wants no hardcoded vocabulary — just easy add/remove of custom
labels, searchable, doubling as a grouping mechanic. Nature facts and review
queues then become labels the operator invents, not schema values. And since a
label about an artwork's nature is about the bytes, a label on one subject
covers identical content everywhere: platform does not matter when bytes are
identical (operator decision 2026-11-15).

### Scope

- Migration: `operator_labels` (unique name, retireable) and
  `operator_label_assertions` (append-only apply/revoke rows, latest-wins).
- Service module + CLI `catalog tag {create,list,remove,apply,revoke,show,search}`
  with JSON output.
- Identical-content expansion at query time: same verified hash pair across file
  seeds; seed↔post and post↔post via identical md5.
- Out of scope: the labeling-server UI (later), suggestions from provider tags
  (later, on top of labels), any propagation to non-identical variants.
