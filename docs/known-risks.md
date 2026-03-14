---
title: Known Risks
tags: [risks, operations]
---

# Known Risks

This document catalogues known operational and technical risks for the lead discovery platform.

## Export Risks

### X1 — Re-export dedup responsibility (Low)

Re-running `leads export` creates a new timestamped file. The tool does not track what has been uploaded to external tools. Callers must add sent email addresses to `suppression_list` before the next export to prevent re-contacting the same leads.

### X2 — No cross-campaign dedup at export (Low)

A contact email that appeared in campaign A and campaign B will appear in both exports. Suppression list is the mechanism to prevent this.

### X3 — Churned leads permanently excluded (Low)

Once `status = churned`, a lead is permanently excluded from export. There is no un-churn transition. If this proves too strict, a manual SQL update is the only recourse.

## Related Notes

- [[pipeline]] — stage flow and CLI commands
- [[export-design]] — full export design and suppression rules
- [[database-schema]] — table definitions
