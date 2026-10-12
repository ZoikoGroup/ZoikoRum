from __future__ import annotations


async def privacy_export(session, identity_id):
    from zoikorum.shared.privacy_exports import export_rows
    from zoikorum.domains.notification.models import Preference, Notification
    return {
        'preferences': await export_rows(session, Preference, Preference.identity_id == identity_id, ['identity_id', 'email', 'in_app', 'sms', 'marketing', 'id', 'updated_at', 'created_at']),
        'notifications': await export_rows(session, Notification, Notification.identity_id == identity_id, ['source_event_id', 'identity_id', 'event_type', 'title', 'body', 'url', 'notice', 'in_app', 'mandatory', 'read_at', 'email_status', 'email_attempts', 'delivered_at', 'last_error', 'id', 'updated_at', 'created_at']),
    }
