# Application review fixes — 14 October 2026

Based on venky commit beab911. Changes are local and have not been pushed.

- Verification reviews: person/firm selection, text search, check/status filters, full history across API pages, and incremental display. Needs-information cases remain visible. Loading feedback, stale-response protection and duplicate-decision protection added.
- Authentication: staff MFA confirmation remains valid for the active session; customer actions retain freshness checks. Sign-in, logout and session revocation checks remain enforced. The development launcher now starts the customer portal on 5173 and staff portal on 5174.
- Messages: preserve request and contract thread records. Once the contract activates, the request becomes read-only; both conversations link to each other and the inbox identifies request history. Active work continues in the engagement conversation. No historical messages or evidence hashes are changed.
- Message attachments: five per message, up to 50 MiB each. Base64 validation and nginx request limits updated together. Sequential uploads provide progress feedback and retain uploaded IDs for retry. Existing type/content checks remain; unsafe document content is still refused.
- Professional discovery: results-container breakpoints, wrapping expertise/action text, and corrected list selectors prevent long labels from overlapping other columns.
- Notifications: optimistic read state and badge update, rollback on failure, refresh after commands, and follow-up refresh for asynchronously produced notices. Message read counts refresh immediately; repeated unchanged read receipts are avoided.

No database migrations are needed. Restart the API and worker, refresh the web app, and run the updated development launcher to start the separate staff frontend. Rebuild the frontend proxy image when deploying the larger message-upload limit.

These changes improve feedback and synchronization; they do not establish a production latency SLO. Other users' activity still arrives through polling. Verification history is fetched across pages (up to the existing allPages safeguard); large deployments should move text/person filtering and aggregate counts to dedicated server queries.

## Validation

- 19 targeted backend integration tests passed (messaging and verification), including the exact 50 MiB attachment boundary and read-only request history. The verification-history test was rerun after the status-filter extension and passed.
- 30 frontend unit tests passed.
- TypeScript and production build passed; lint passed with existing warnings.
- Three new Playwright checks passed: person-wise review selection; professional-list bounds at 1880, 1440, 1024 and 700 pixels; optimistic notification read and bell state while the server reply is deliberately held.
- PowerShell startup-script syntax and whitespace checks for the changed implementation files passed. Pre-existing run-tests.ps1 edits were preserved.
- Chromium was installed for browser checks. The test-server startup timeout is optionally configurable with ZK_E2E_STARTUP_TIMEOUT_MS; the successful local run used 600000. The ordinary default remains 120000.

## Staff session confirmation update

Staff MFA confirmation now remains valid for the active, validated session rather than expiring after five minutes. Password-only staff access remains blocked. Logout, account restrictions, session revocation, JWT verification and session expiry continue to be enforced by the existing session validator. Customer actions retain the configured freshness window; an explicitly requested maximum age also remains enforced. Existing MFA-backed staff sessions use the new behavior after the API restarts, including across token refreshes.
