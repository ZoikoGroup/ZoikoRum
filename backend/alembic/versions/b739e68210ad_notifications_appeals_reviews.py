"""Notification delivery, dispute appeals and verified reviews."""
from alembic import op

revision = "b739e68210ad"
down_revision = "d04537c7a0f4"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS review")
    op.execute('\nCREATE TABLE notification.notifications (\n\tsource_event_id UUID NOT NULL, \n\tidentity_id UUID NOT NULL, \n\tevent_type VARCHAR(160) NOT NULL, \n\ttitle VARCHAR(200) NOT NULL, \n\tbody TEXT NOT NULL, \n\turl VARCHAR(500) NOT NULL, \n\tnotice JSONB, \n\tin_app BOOLEAN NOT NULL, \n\tmandatory BOOLEAN NOT NULL, \n\tread_at TIMESTAMP WITH TIME ZONE, \n\temail_status VARCHAR(20) NOT NULL, \n\temail_attempts INTEGER NOT NULL, \n\tdelivered_at TIMESTAMP WITH TIME ZONE, \n\tlast_error VARCHAR(300), \n\tid UUID NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_notifications PRIMARY KEY (id), \n\tCONSTRAINT uq_notifications_source_event_id_identity_id UNIQUE (source_event_id, identity_id)\n)\n\n')
    op.execute('\nCREATE TABLE notification.webhook_endpoints (\n\torganization_id UUID NOT NULL, \n\turl VARCHAR(2000) NOT NULL, \n\tsecret_encrypted TEXT NOT NULL, \n\tevent_types JSONB NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_webhook_endpoints PRIMARY KEY (id)\n)\n\n')
    op.execute('\nCREATE TABLE notification.webhook_deliveries (\n\tendpoint_id UUID NOT NULL, \n\tsource_event_id UUID NOT NULL, \n\tbody JSONB NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tretry_until TIMESTAMP WITH TIME ZONE NOT NULL, \n\tdelivered_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_webhook_deliveries PRIMARY KEY (id), \n\tCONSTRAINT uq_webhook_deliveries_endpoint_id_source_event_id UNIQUE (endpoint_id, source_event_id), \n\tCONSTRAINT fk_webhook_deliveries_endpoint_id_webhook_endpoints FOREIGN KEY(endpoint_id) REFERENCES notification.webhook_endpoints (id)\n)\n\n')
    op.execute('\nCREATE TABLE notification.delivery_attempts (\n\tdelivery_id UUID NOT NULL, \n\tresponse_status INTEGER, \n\terror VARCHAR(300), \n\tattempt INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_delivery_attempts PRIMARY KEY (id), \n\tCONSTRAINT fk_delivery_attempts_delivery_id_webhook_deliveries FOREIGN KEY(delivery_id) REFERENCES notification.webhook_deliveries (id)\n)\n\n')
    op.execute('\nCREATE TABLE dispute.appeals (\n\tcase_id UUID NOT NULL, \n\tsubmitted_by UUID NOT NULL, \n\tgrounds VARCHAR(40) NOT NULL, \n\texplanation VARCHAR(4000) NOT NULL, \n\tevidence JSONB NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\treviewed_by UUID, \n\tdecision_reason VARCHAR(4000), \n\tremediation VARCHAR(4000), \n\tdecided_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_appeals PRIMARY KEY (id), \n\tCONSTRAINT uq_appeals_case_id UNIQUE (case_id), \n\tCONSTRAINT fk_appeals_case_id_cases FOREIGN KEY(case_id) REFERENCES dispute.cases (id)\n)\n\n')
    op.execute('\nCREATE TABLE review.reviews (\n\tcontract_id UUID NOT NULL, \n\torganization_id UUID NOT NULL, \n\tprofessional_id UUID NOT NULL, \n\treviewer_identity_id UUID NOT NULL, \n\treviewer_name VARCHAR(200) NOT NULL, \n\torganization_name VARCHAR(200) NOT NULL, \n\trating INTEGER NOT NULL, \n\tcomment VARCHAR(2000) NOT NULL, \n\tengagement_reference VARCHAR(40) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_reviews PRIMARY KEY (id), \n\tCONSTRAINT uq_reviews_contract_id UNIQUE (contract_id)\n)\n\n')
    op.execute('CREATE INDEX ix_notifications_recipient ON notification.notifications (identity_id, created_at)')
    op.execute('CREATE INDEX ix_notification_webhook_endpoints_organization_id ON notification.webhook_endpoints (organization_id)')
    op.execute('CREATE INDEX ix_notification_delivery_attempts_delivery_id ON notification.delivery_attempts (delivery_id)')
    op.execute('CREATE INDEX ix_review_reviews_professional_id ON review.reviews (professional_id)')
    op.execute('CREATE TRIGGER prevent_mutation BEFORE UPDATE OR DELETE ON notification.delivery_attempts FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation()')
    op.execute('CREATE TRIGGER prevent_mutation BEFORE UPDATE OR DELETE ON review.reviews FOR EACH ROW EXECUTE FUNCTION platform.prevent_mutation()')

def downgrade():
    op.drop_table('reviews', schema='review')
    op.drop_table('appeals', schema='dispute')
    op.drop_table('delivery_attempts', schema='notification')
    op.drop_table('webhook_deliveries', schema='notification')
    op.drop_table('webhook_endpoints', schema='notification')
    op.drop_table('notifications', schema='notification')
