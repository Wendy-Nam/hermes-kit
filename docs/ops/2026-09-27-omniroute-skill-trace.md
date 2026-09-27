# OmniRoute ↔ Hermes trace audit, 2026-09-27

Read-only provider trace inspection; no diagnostic generation or external messages sent. Secrets and conversation bodies are omitted from this report.

## Observed traffic (17:00–20:13 KST)

Excluded connection-test health checks. 119 recorded model calls, all HTTP 200:

| Combo | Actual target | Calls | Mean / max provider duration |
|---|---|---:|---|
| hermes-chat | codex/gpt-6-luna | 97 | 4.835s / 12.384s |
| hermes-private | mistral/codestral-latest | 14 | 2.407s / 4.926s |
| hermes-coding | experiential/gpt-5.6-luna | 8 | 2.668s / 4.041s |

HTTP success is not task completion. Call summaries live in SQLite call_logs, while raw request/response details are JSON artifacts under call_logs/YYYY-MM-DD, not the empty request_detail_logs table.

## Incorrect prior deployment conclusion

The 19:47:50 and 19:48:05 requests were sent after the 19:27 gateway restart. Their actual system prompt still contained the old unconditional skill loading instruction and did not contain the new reuse-or-load rule. The source file was patched, but existing session prompts are content-addressed in system_prompts and referenced by sessions.system_prompt_hash. A NULL sessions.system_prompt column does NOT mean no saved prompt. Both inspected sessions resolved to a 26,561-character old prompt.

The same requests included one full san-conversation-guardrails tool result and two earlier deduplicated stubs. Neither new response called skill_view: the first called memory and the second answered. This establishes that old instructions remained, not that these two new calls repeated the skill lookup.

Latest chat request carried approximately 65.9k input tokens; reported cache read ratio was 94–99% on those two calls. The retained full skill body is ordinary conversation history, distinct from a fresh skill_view call. Repeated stubs do not eliminate model round trips.

## 20:00 autonomous execution

Eight hermes-coding requests completed at the transport layer. Hermes actually inspected the recovered inbox item and reported RESULT blocked because the requested monitoring implementation/configuration/measurement baseline was absent. Inbox status is now dropped=2, open=1, stale claimed=0. No self-selected new goal was created; autonomous research success is not established merely by scheduler status=ok.

## Corrective deployment

Extended the persistent patch to migrate the exact generated Skills introduction when restoring saved prompts, then persist through Hermes' normal API. It requires the generated section heading and skills roster and leaves unrelated prompt bytes unchanged. Nine regression tests passed, including migration idempotency and preservation checks.

After verifying idle gateway and no active cron executions, stopped gateway-default, backed up the two resolved original prompts in server-only .backups/skill-prompt-migration-20260927 (restricted permissions), and updated both using SessionDB.update_system_prompt. Readback verified 26,561→26,918 characters, old instruction absent and new instruction present. Restarted the supervised gateway. No user message, model test request, or public delivery was sent. Subsequent real-turn request capture remains the final behavioral verification; prompt changes do not categorically prohibit a model from calling skill_view.
