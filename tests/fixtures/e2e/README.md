# E2E Fixtures

Small fictional datasets that mirror the real local file shapes used by the
operator workflow:

- Panorama compliance history: 14 columns.
- PEAR processed overdue, suspension, and suspension-vs-overdue: 7/7/8 columns.
- School reference: JSON list with wave and suspension-window authority.
- Workdays: CSV with suspension-window and previous-business-day mappings.

These files are intentionally tiny and contain no real people, schools, or
client identifiers.

The 2026-02-23 and 2026-02-24 files are paired so tests can exercise
previous-business-day continuity without reaching into local private data.
