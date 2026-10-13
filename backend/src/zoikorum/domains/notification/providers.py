"""Email adapters and pinned-public-address webhook delivery."""
from __future__ import annotations

import asyncio
import http.client
import ipaddress
import logging
import smtplib
import socket
import ssl
from email.message import EmailMessage
from urllib.parse import urlsplit

from zoikorum.config import get_settings
from zoikorum.shared.errors import ValidationFailed


class ConsoleEmailProvider:
    async def send(self, recipient, subject, body, message_id):
        # Purpose tokens and private message content must never enter logs.
        logging.getLogger(__name__).info("Development email %s: %s", message_id, subject)
        return "LOCAL_ONLY"


class SMTPEmailProvider:
    async def send(self, recipient, subject, body, message_id):
        settings = get_settings()
        if not settings.smtp_host:
            raise RuntimeError("SMTP host is not configured")
        message = EmailMessage()
        message['From'], message['To'], message['Subject'] = settings.email_from, recipient, subject
        message['Message-ID'] = f"<{message_id}@zoikorum.com>"
        message.set_content(body)
        def transmit():
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                if settings.smtp_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password or '')
                refused = smtp.send_message(message)
                if refused:
                    raise RuntimeError("Mail server refused recipient")
        await asyncio.to_thread(transmit)
        return "DELIVERED"


def email_provider():
    settings = get_settings()
    if settings.env == 'test' or settings.email_provider == 'console':
        return ConsoleEmailProvider()
    if settings.email_provider == 'smtp':
        return SMTPEmailProvider()
    raise RuntimeError("Unknown email provider")


def checked_url(url):
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ValidationFailed("Enter a valid public HTTPS URL") from exc
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValidationFailed("Webhook URLs must use HTTPS, without credentials or fragments")
    try:
        if parsed.port not in (None, 443):
            raise ValueError()
    except ValueError as exc:
        raise ValidationFailed("Webhook URLs must use port 443") from exc
    if parsed.hostname.lower() in {'localhost', 'localhost.localdomain'}:
        raise ValidationFailed("Webhook destinations must be public")
    try:
        literal_address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal_address = None
    if literal_address is not None and not literal_address.is_global:
        raise ValidationFailed("Webhook destinations must be public")
    return parsed


async def post_webhook(url, body, headers):
    parsed = checked_url(url)
    def transmit():
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("Webhook destination must resolve exclusively to public addresses")
        pinned_ip = addresses[0][4][0]
        class PinnedHTTPS(http.client.HTTPSConnection):
            def connect(self):
                raw = socket.create_connection((pinned_ip, 443), timeout=10)
                self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=parsed.hostname)
        connection = PinnedHTTPS(parsed.hostname, timeout=10)
        try:
            path = parsed.path or '/'
            if parsed.query:
                path += '?' + parsed.query
            connection.request('POST', path, body=body, headers=headers)
            response = connection.getresponse()
            status = response.status
            response.read(4096)
            return status  # redirects are failures; never follow them
        finally:
            connection.close()
    return await asyncio.to_thread(transmit)
