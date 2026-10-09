"""Settings that pass the staging/production checks (config._real_secrets_outside_development), for tests that need
a production configuration. Test values only."""

PRODUCTION = {
    "env": "production",
    "jwt_secret": "test-only-jwt-secret-0123456789abcdef",
    "field_encryption_key": "test-only-field-key-0123456789abcdef",
    "webhook_secret": "test-only-webhook-secret-0123456789",
    "frontend_url": "https://app.zoikorum.test",
}
