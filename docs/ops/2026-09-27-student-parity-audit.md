# Student image parity audit — 2026-09-27

Audited released ghcr.io/wendy-nam/hermes-kit:0.21.2-k4, not merely the personal server checkout.

| Change or feature | Student status | Action |
|---|---|---|
| Personal default delegation10→40 | Released Hermes DEFAULT_CONFIG and delegate_tool default both250; kit seed does not override delegation | Do not transplant a lower personal limit. Explicit student limits remain preserved when enabling OmniRoute. |
| Stored skill prompt reuse migration | Included in Docker build and CI runtime migration smoke in k4 | Retained; local core tests pass. |
| Live snow keyword freshness and FTS compatibility | Personal third-party plugin excluded from student image; secret scan prohibits it | No private plugin copied. Adding retrieval later needs an explicitly distributable implementation and equivalent regression coverage. |
| RTK | RTK0.50.0 pinned; first boot installs official Hermes plugin with rtk init | Already included. Personal RTK0.43.0 deployment stats do not describe student runtime. |
| Caveman output style | No compulsory personal compression profile in installer | Retain opt-in behavior; synthetic personal experiment did not establish universal savings. |
| Per-task OMH model selection | Personal incident skipped prepared per-dispatch routing; not fixed by raising budget | Open orchestration issue, not certified solved in either deployment. |
| Personal conversations, profiles, self plugin, credentials | Not copied | Preserve existing distribution exclusions. |

Verification: imported DEFAULT_CONFIG from the released image in a temporary isolated home with network disabled: delegation.max_iterations250, max_concurrent_children10, max_summary_chars24000. Student config overlay does not lower these delegation limits. The displayed image's tool fallback DEFAULT_MAX_ITERATIONS is also250. Local core tests18/18 and OmniRoute setup tests10/10 passed. Setup test confirms an explicit user iteration limit remains unchanged while routing is configured. No release rebuild was needed for this audit; no runtime package change was made.
