import ipaddress
import smtplib
import socket
from email.message import EmailMessage

from app.core.crypto import decrypt_secret
from app.models.email_account import EmailAccount

SMTP_PORTS = {25, 465, 587, 2525}


class EmailSendError(Exception):
    pass


def validate_smtp_server(host: str, port: int) -> None:
    """Only public mail servers on standard SMTP ports - the host is user-supplied, so it
    must not become a way to reach internal network services."""
    if port not in SMTP_PORTS:
        raise ValueError(f"SMTP port must be one of {sorted(SMTP_PORTS)}")
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        raise ValueError("Cannot resolve the SMTP server") from e
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Private, local and reserved network addresses are not allowed")


def send_email(account: EmailAccount, to_email: str, subject: str, body: str) -> None:
    message = EmailMessage()
    from_header = f"{account.from_name} <{account.from_email}>" if account.from_name else account.from_email
    message["From"] = from_header
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    try:
        validate_smtp_server(account.smtp_host, account.smtp_port)
        password = decrypt_secret(account.encrypted_password)
        if account.smtp_port == 465:
            smtp = smtplib.SMTP_SSL(account.smtp_host, account.smtp_port, timeout=15)
        elif account.use_tls:
            smtp = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=15)
        else:
            raise ValueError("TLS is required; the password is never sent unencrypted")
        with smtp:
            if account.smtp_port != 465:
                smtp.starttls()
            smtp.login(account.smtp_username, password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError, ValueError) as e:
        raise EmailSendError(str(e)) from e
