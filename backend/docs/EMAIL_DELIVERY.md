# Transactional email delivery

Development/test console delivery is LOCAL_ONLY. Console delivery fails closed outside development. SMTP acceptance is ACCEPTED; it does not prove inbox delivery.

For SendGrid set `ZK_EMAIL_PROVIDER=sendgrid`, `ZK_SENDGRID_API_KEY`, `ZK_SENDGRID_WEBHOOK_PUBLIC_KEY` and `ZK_EMAIL_FROM`. Verify the sending domain in the provider account. Enable signed event delivery to `${ZK_PUBLIC_API_URL}/v1/webhooks/sendgrid` for processed, deferred, delivered, bounce, dropped, spam-report and unsubscribe events. The webhook public key is SendGrid’s base64 DER ECDSA key.

The adapter attaches the notification UUID as a custom argument. Receipts verify the timestamp/signature against the raw bytes, bind to the recipient, deduplicate provider event IDs and retain only event metadata/payload hashes. Late processed/delivered events cannot reverse bounce/suppression state. Hard bounces, complaints and unsubscribe events suppress further email to the hashed address; in-app mandatory notices remain available. SMTP has no provider delivery receipts through this adapter.

Owners can see email status in Notifications and query their notification’s receipt history. Tokens and private email bodies are excluded from logs and receipt records. Delivery uses at-least-once worker execution; SendGrid acceptance alone is not a guarantee against duplicate email after a lost database commit.

Protocol references: [signed event verification](https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/getting-started-event-webhook-security-features), [mail-send custom arguments](https://www.twilio.com/docs/sendgrid/api-reference/mail-send/mail-send).
