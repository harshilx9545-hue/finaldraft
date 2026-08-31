"""Non-blocking mail helper.

Mail that is not required for an operation to be correct must never fail that
operation. A registration that succeeded in the database but returned 500 because
SMTP was down leaves the user unable to retry (the email is taken) and unable to
proceed. So transport errors are caught, logged with recipient and message type on
the `core.auth` logger, and swallowed (8.6).

The return value says whether delivery was attempted successfully, for callers
that want to surface "we could not email you" as information rather than failure.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger("core.auth")

#: Message types, so log lines are greppable and the property test can assert the
#: type appears in the record.
VERIFY_EMAIL = "email_verification"
PASSWORD_RESET = "password_reset"
MEMBER_INVITE = "member_invite"
TRAINER_INVITE = "trainer_invite"
INVOICE_ISSUED = "invoice_issued"
PAYMENT_RECEIPT = "payment_receipt"


def send_optional(recipient, subject, body, message_type, html_body=None):
    """Send mail, never raise. Returns True when the backend accepted the message.

    Deliberately catches `Exception`: backends raise SMTPException, socket errors,
    ssl errors, and their own wrappers, and the whole point is that none of them
    reach the caller.
    """
    if not recipient:
        logger.warning("mail skipped type=%s reason=no_recipient", message_type)
        return False

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or "no-reply@localhost"

    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=from_email,
            to=[recipient],
        )
        if html_body:
            message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001 - see docstring
        # Recipient and message type are logged; the body is not, because reset
        # and verification bodies contain single-use tokens.
        logger.error(
            "mail failed recipient=%s type=%s error=%s",
            recipient,
            message_type,
            exc.__class__.__name__,
            exc_info=False,
        )
        return False

    logger.info("mail sent recipient=%s type=%s", recipient, message_type)
    return True


def send_verification_email(user, raw_token):
    return send_optional(
        recipient=user.email,
        subject="Verify your email address",
        body=(
            "Confirm your email address to finish setting up your account.\n\n"
            f"Verification code: {raw_token}\n\n"
            "This code expires in 72 hours."
        ),
        message_type=VERIFY_EMAIL,
    )


def send_password_reset_email(user, raw_token):
    return send_optional(
        recipient=user.email,
        subject="Reset your password",
        body=(
            "A password reset was requested for your account.\n\n"
            f"Reset code: {raw_token}\n\n"
            "This code expires in 60 minutes. If you did not request it, no action "
            "is needed."
        ),
        message_type=PASSWORD_RESET,
    )


def send_invite_email(user, gym, raw_password, message_type):
    return send_optional(
        recipient=user.email,
        subject=f"You have been added to {gym.name}",
        body=(
            f"An account has been created for you at {gym.name}.\n\n"
            f"Email: {user.email}\n"
            f"Temporary password: {raw_password}\n\n"
            "Please sign in and change it."
        ),
        message_type=message_type,
    )
