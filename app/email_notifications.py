from email.utils import parseaddr
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from email_validator import EmailNotValidError, validate_email
from flask import current_app, url_for


RESEND_TEST_SENDER = "onboarding@resend.dev"
RESEND_TEST_RECIPIENT = "delivered@resend.dev"


def _absolute_url(endpoint, **values):
    base_url = current_app.config["PUBLIC_BASE_URL"].rstrip("/") + "/"
    return urljoin(
        base_url,
        url_for(endpoint, **values).lstrip("/"),
    )


def _send_email(recipient, subject, body, context):
    if not isinstance(recipient, str) or not recipient.strip():
        current_app.logger.warning(
            "Email skipped for %s: recipient is missing", context
        )
        return False

    try:
        recipient = validate_email(
            recipient.strip(),
            check_deliverability=False,
        ).normalized
    except EmailNotValidError:
        current_app.logger.warning(
            "Email skipped for %s: recipient is invalid", context
        )
        return False

    api_key = current_app.config.get("RESEND_API_KEY")
    sender = current_app.config.get("RESEND_FROM")
    test_mode = (
        str(current_app.config.get("RESEND_TEST_MODE", False)).lower() == "true"
    )

    if (
        not isinstance(api_key, str)
        or not api_key.strip()
        or "\r" in api_key
        or "\n" in api_key
    ):
        current_app.logger.warning(
            "Email skipped for %s: RESEND_API_KEY is missing or invalid",
            context,
        )
        return False

    if test_mode:
        configured_test_recipient = current_app.config.get(
            "RESEND_TEST_RECIPIENT", RESEND_TEST_RECIPIENT
        )
        if configured_test_recipient != RESEND_TEST_RECIPIENT:
            current_app.logger.warning(
                "Email skipped for %s: test mode only permits the Resend "
                "documented test recipient",
                context,
            )
            return False
        recipient = RESEND_TEST_RECIPIENT
        sender = RESEND_TEST_SENDER
        body = re.sub(
            r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
            "[redacted email]",
            body,
        )
    elif (
        not isinstance(sender, str)
        or not sender.strip()
        or "\r" in sender
        or "\n" in sender
    ):
        current_app.logger.warning(
            "Email skipped for %s: RESEND_FROM is missing",
            context,
        )
        return False
    else:
        sender_email = parseaddr(sender)[1]
        try:
            validated_sender = validate_email(
                sender_email,
                check_deliverability=False,
            ).normalized
        except EmailNotValidError:
            current_app.logger.warning(
                "Email skipped for %s: RESEND_FROM is invalid",
                context,
            )
            return False
        if validated_sender.casefold().endswith("@resend.dev"):
            current_app.logger.warning(
                "Email skipped for %s: the Resend testing sender is only "
                "allowed when RESEND_TEST_MODE=true",
                context,
            )
            return False

    payload = {
        "from": sender.strip(),
        "to": [recipient],
        "subject": subject,
        "text": body,
    }

    request = Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=8) as response:
            response.read()

            if 200 <= response.status < 300:
                current_app.logger.info(
                    "Email accepted by provider for %s", context
                )
                return True

            current_app.logger.warning(
                "Email API returned HTTP %s for %s",
                response.status,
                context,
            )

    except HTTPError as error:
        error_name, error_message = _resend_error_details(
            error,
            secrets_to_redact=(api_key, recipient),
        )
        current_app.logger.warning(
            "Resend rejected %s (HTTP %s, error=%s): %s",
            context,
            error.code,
            error_name,
            error_message,
        )
    except TimeoutError:
        current_app.logger.warning("Resend request timed out for %s", context)
    except URLError as error:
        if isinstance(error.reason, TimeoutError):
            current_app.logger.warning(
                "Resend request timed out for %s",
                context,
            )
        else:
            current_app.logger.warning(
                "Resend request failed for %s (%s)",
                context,
                type(error).__name__,
            )
    except (OSError, ValueError, TypeError) as error:
        current_app.logger.warning(
            "Resend request failed for %s (%s)",
            context,
            type(error).__name__,
        )

    return False


def _resend_error_details(error, secrets_to_redact=()):
    error_name = "unknown"
    error_message = "No safe error detail was returned"
    try:
        response_data = json.loads(error.read(4096).decode("utf-8"))
    except (AttributeError, OSError, UnicodeDecodeError, ValueError):
        response_data = None

    if isinstance(response_data, dict):
        error_name = (
            response_data.get("name")
            or response_data.get("type")
            or error_name
        )
        error_message = (
            response_data.get("message")
            or response_data.get("error")
            or error_message
        )

    def sanitize(value):
        text = str(value)
        for secret in secrets_to_redact:
            if isinstance(secret, str) and secret:
                text = text.replace(secret, "[redacted]")
        text = re.sub(r"(?i)\bbearer\s+\S+", "Bearer [redacted]", text)
        text = re.sub(
            r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
            "[email]",
            text,
        )
        text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
        return " ".join(text.split())[:400] or "No safe error detail was returned"

    return sanitize(error_name), sanitize(error_message)


def _send_listing_email(product_id, recipient, subject, body):
    return _send_email(
        recipient,
        subject,
        body,
        f"listing product id {product_id}",
    )


def notify_admin_listing_submitted(product):
    admin_email = (
        current_app.config.get("ADMIN_NOTIFICATION_EMAIL")
        or current_app.config.get("SUPPORT_EMAIL")
        or current_app.config.get("MAIL_USERNAME")
    )

    category_name = (
        product.category.name if product.category else "Not specified"
    )
    review_url = _absolute_url("admin.products")

    body = (
        "A student listing is waiting for approval.\n\n"
        f"Title: {product.title}\n"
        f"Price: ₹{product.price:.2f}\n"
        f"Category: {category_name}\n"
        f"Student: {product.seller.name}\n\n"
        f"Review listings: {review_url}\n"
    )

    return _send_listing_email(
        product.id,
        admin_email,
        "Student listing waiting for approval",
        body,
    )


def notify_student_listing_moderated(product, approval_status):
    seller_email = product.seller.university_email
    listing_url = _absolute_url(
        "products.detail", product_id=product.id
    )

    body = (
        f"Your listing, “{product.title}”, was "
        f"{approval_status} by an administrator.\n\n"
        f"View your listing: {listing_url}\n"
    )

    return _send_listing_email(
        product.id,
        seller_email,
        f"Your listing was {approval_status}",
        body,
    )


def notify_account_suspended(user):
    support_email = (
        current_app.config.get("SUPPORT_EMAIL")
        or current_app.config.get("MAIL_USERNAME")
    )

    support_paragraph = (
        "\nIf you have questions, contact our support team at:\n\n"
        f"{support_email}\n"
        if support_email
        else ""
    )

    body = (
        f"Hello {user.name},\n\n"
        "Your Student Second-Hand Marketplace account has been "
        "suspended by the administrator.\n\n"
        "You may be unable to access marketplace features while your "
        "account is suspended.\n"
        "If you believe this decision was made in error, you may "
        "request a review.\n"
        f"{support_paragraph}\n"
        "Please do not send your password or authentication credentials.\n\n"
        "Regards,\n"
        "Student Second-Hand Marketplace Support Team\n"
    )

    return _send_email(
        user.university_email,
        "Important: Your marketplace account has been suspended",
        body,
        f"account suspension user id {user.id}",
    )


def notify_student_account_activated(user):
    student_name = " ".join((user.name or "").split()) or "there"
    support_email = (
        current_app.config.get("SUPPORT_EMAIL")
        or current_app.config.get("MAIL_USERNAME")
    )

    support_paragraph = (
        "\nIf you need assistance, contact our support team at:\n\n"
        f"{support_email}\n"
        if support_email
        else ""
    )

    body = (
        f"Hello {student_name},\n\n"
        "Good news! Your Student Second-Hand Marketplace account has "
        "been reactivated by the administrator.\n\n"
        "You can now log in again and access the marketplace features "
        "available to your account.\n"
        f"{support_paragraph}\n"
        "Thank you for being part of the Student Second-Hand Marketplace.\n\n"
        "Regards,\n"
        "Student Second-Hand Marketplace Support Team\n"
    )

    return _send_email(
        user.university_email,
        "Your Student Second-Hand Marketplace Account Has Been Reactivated",
        body,
        f"account reactivation user id {user.id}",
    )


def notify_student_registered(user):
    student_name = " ".join((user.name or "").split()) or "there"
    body = (
        f"Hello {student_name},\n\n"
        "Welcome to Student Second-Hand Marketplace!\n\n"
        "Your account has been created successfully. Your account is "
        "currently awaiting administrator verification.\n\n"
        "Once the administrator verifies your account, you will receive "
        "another email confirming that your marketplace access is available.\n\n"
        "Thank you for joining our student community!\n\n"
        "Regards,\n"
        "Student Second-Hand Marketplace Team\n"
    )
    return _send_email(
        user.university_email,
        "Your Student Second-Hand Marketplace Account Has Been Created",
        body,
        f"registration user id {user.id}",
    )


def notify_admin_new_student_registration(user):
    registration_date = user.created_at.strftime("%Y-%m-%d %H:%M UTC")
    admin_url = _absolute_url("admin.users")
    body = (
        "Hello Administrator,\n\n"
        "A new student has registered on Student Second-Hand Marketplace "
        "and is awaiting verification.\n\n"
        "Student Details:\n\n"
        f"- Name: {user.name}\n"
        f"- University Email: {user.university_email}\n"
        f"- Registration Date: {registration_date}\n\n"
        "Please review the student's account and verify it through the "
        f"administration dashboard:\n{admin_url}\n\n"
        "Regards,\n"
        "Student Second-Hand Marketplace System\n"
    )
    return _send_email(
        current_app.config.get("ADMIN_NOTIFICATION_EMAIL"),
        "New Student Registration — Verification Required",
        body,
        f"new student registration user id {user.id}",
    )


def notify_student_account_verified(user):
    student_name = " ".join((user.name or "").split()) or "there"
    marketplace_url = _absolute_url("products.home")
    access_message = (
        "You can now access the marketplace and participate in the "
        "student community."
        if user.is_active
        else "Your account is verified, but it remains suspended. An "
        "administrator must reactivate it before you can access the "
        "marketplace."
    )
    body = (
        f"Hello {student_name},\n\n"
        "Congratulations! Your Student Second-Hand Marketplace account "
        "has been successfully verified by the administrator.\n\n"
        f"{access_message}\n\n"
        "With your verified account, you can:\n\n"
        "- Sell items: List used books, laptops, calculators, engineering "
        "kits, and other permitted items.\n"
        "- Rent items: Make eligible items available for rent or rent items "
        "listed by other students.\n"
        "- Buy items: Browse listings and purchase available items.\n"
        "- List products: Submit your own listings for administrator "
        "approval, if required by the existing marketplace rules.\n\n"
        "Visit the marketplace to get started:\n\n"
        f"{marketplace_url}\n\n"
        "Thank you for being part of our student community!\n\n"
        "Regards,\n"
        "Student Second-Hand Marketplace Team\n"
    )
    return _send_email(
        user.university_email,
        "Your Student Second-Hand Marketplace Account Has Been Verified!",
        body,
        f"account verification user id {user.id}",
    )