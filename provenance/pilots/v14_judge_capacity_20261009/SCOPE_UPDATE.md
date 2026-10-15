# Scope update before study dispatch

2026-10-09. Claude's metadata GET returned HTTP 401. No Claude generation,
capacity probe or study judgment was sent. The user then explicitly asked to
skip Claude. Its offered credential was not written to disk or zshrc and was
discarded from the working in-memory variable after the failed check.

The remaining study scope is Mistral only: a new, separately frozen enlarged-cap
method, 140 planned study requests after a qualified capacity preflight.
The prepared Sonnet adapter remains implementation/test-only, not a qualified
or executed evaluation. Its metadata failure is retained outside study counts.

No credential is included in the metadata receipt. No automatic retry or
alternative endpoint is attempted. Older OpenAI/Gemini judgments are reused,
and the old Mistral4k failures remain a separate historical method.
