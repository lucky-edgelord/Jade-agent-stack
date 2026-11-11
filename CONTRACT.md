# CONTRACT.md: Vault ↔ Base

One page. The rules every part of the Jade stack keeps. No code here; the tests are the specification.

**Vault asks. Base answers. Base logs. Base can say no.**

| Topic | Rule |
| --- | --- |
| Roles | Vault is the control plane: the agent loop, schedules, heartbeat, autonomy, budgets, approvals, the person. Base is the resource plane: identity, data, the model gateway, billing, the audit log. Base hosts no agent and runs no schedules. Kit is the embeddable subset of Vault. |
| Protocol | MCP over HTTP at Base's `/api/agent/mcp`; the same tools over REST at `/api/agent/tools/{name}`. No other protocol. |
| The transcript | Vault owns what the person sees and said. Base never stores conversations on Vault's behalf. |
| The audit log | Base's `agent_audit` is authoritative: every tool call, its arguments with secrets redacted, the result or error, the task and idempotency key, replays, and refusals. Agents cannot change it. |
| Requests | Vault (or the toolkit, or Kit) sends one tool call with its arguments; Base validates, checks scopes, runs it, logs it and answers. |
| Refusal | Base says no with a reason: a missing scope (403), a refused credential (403 `credential_refused`), invalid arguments (400), a reused key (422). A client that gets a refusal stops and tells the person. It does not retry around it. |
| Task identity | Every task, flow run or scheduled job has a `task_id`, minted by Vault. It travels in the task credential and appears in the audit log. |
| Credentials | Vault mints one task credential per task (`POST /api/agent/credentials`): least privilege (a subset of the agent's scopes), a bounded TTL (15 min default, 24 h max). Revocation is checked on every request and fails closed. Long-lived agent tokens stay in Vault. Tokens travel only in the `Authorization` header, never in a URL. |
| Idempotency | Every mutating call carries an idempotency key. Base runs a key once per caller and replays the first answer for 24 h. Reads may retry; mutations are not retried automatically. |
| Resumability | A task's progress is recorded by the client (which steps finished, with which keys). After an interruption, the task resumes: finished steps are skipped, unfinished ones are sent again with the same keys, so nothing runs twice. |
| Phone sleeps mid-flow | The run stops where it is. Its credential may expire meanwhile. On wake, Vault mints a new credential for the same `task_id` and resumes with the same keys; Base replays any call that had already reached it. |
| Approvals | Vault owns the approval model (pattern-scoped, deny wins, every approval recorded with what, scope, target, time, task, and whether a person was present). Base enforces scopes; the toolkit enforces its local copy before a call leaves. Server-side approval being silenced never disables local enforcement. |
| Versions | STACK.md says which versions work together; a major mismatch is refused. |
