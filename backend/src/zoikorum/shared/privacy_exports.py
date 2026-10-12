"""Serialization only; each owning domain supplies its explicit authorised query."""
from sqlalchemy import select
from pydantic_core import to_jsonable_python

SECRET_FIELDS = {'password_hash', 'mfa_secret_enc', 'refresh_token_hash', 'token_hash', 'secret_enc',
                 'provider_ref', 'provider_account_ref', 'transfer_ref', 'storage_key', 'storage_version', 'photo_key',
                 'public_key', 'credential_id', 'challenge', 'document', 'ip', 'phone_enc',
                 'storageKey', 'storageVersion', 'accessToken', 'refreshToken', 'token', 'secret'}

def portable(value):
    if isinstance(value, dict):
        return {k: portable(v) for k, v in value.items() if k not in SECRET_FIELDS and not k.endswith('_enc')}
    if isinstance(value, (list, tuple)):
        return [portable(v) for v in value]
    return to_jsonable_python(value)

async def export_rows(session, model, condition, fields):
    rows = (await session.scalars(select(model).where(condition).order_by(model.id))).all()
    return [{field: portable(getattr(row, field)) for field in fields if field not in SECRET_FIELDS} for row in rows]
