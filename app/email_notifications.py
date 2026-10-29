import re
from email.utils import parseaddr
from urllib.parse import urljoin

import requests
from email_validator import EmailNotValidError, validate_email
from flask import current_app, url_for


RESEND_TEST_SENDER = "onboarding@resend.dev"
RESEND_TEST_RECIPIENT = "delivered@resend.dev"


def _absolute_url(endpoint, **values):
    base_url = current_app.config["PUBLIC_BASE_URL"].rstrip("/") + "/"
    return urljoin(base_url, url_for(endpoint, **values).lstrip("/"))


def _sanitize_error(value, secrets_to_redact=()):
    text = str(value or "")

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

    return " ".join(text.split())[:400] or "No safe error detail returned"


def _send_email(recipient, subject, body, context):
    api_key = current_app.config.get("RESEND_API_KEY")
    api_key = api_key.strip() if isinstance(api_key, str) else ""

    if not api_key or "\r" in api_key or "\n" in api_key:
        current_app.logger.warning(
            "Email skipped for %s: RESEND_API_KEY is missing or invalid",
            context,
        )
        return False

    raw_test_mode = current_app.config.get("RESEND_TEST_MODE", False)
    test_mode = (
        raw_test_mode is True
        or str(raw_test_mode).strip().lower() == "true"
    )

    if test_mode:
        if recipient is not None and (
            not isinstance(recipient, str) or recipient.strip()
        ):
            if not isinstance(recipient, str):
                current_app.logger.warning(
                    "Email skipped for %s: recipient is invalid",
                    context,
                )
                return False

            try:
                validate_email(
                    recipient.strip(),
                    check_deliverability=False,
                )
            except EmailNotValidError:
                current_app.logger.warning(
                    "Email skipped for %s: recipient is invalid",
                    context,
                )
                return False

        sender = RESEND_TEST_SENDER
        recipient = (
            current_app.config.get("RESEND_TEST_RECIPIENT")
            or RESEND_TEST_RECIPIENT
        )

        try:
            recipient = validate_email(
                recipient,
                check_deliverability=False,
            ).normalized
        except (EmailNotValidError, TypeError):
            current_app.logger.warning(
                "Email skipped for %s: test recipient is invalid",
                context,
            )
            return False

        if not recipient.casefold().endswith("@resend.dev"):
            current_app.logger.warning(
                "Email skipped for %s: test recipient must use "
                "Resend's resend.dev test domain",
                context,
            )
            return False

        # Do not expose real student or administrator addresses in test emails.
        body = re.sub(
            r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
            "[redacted email]",
            body,
        )

    else:
        if not isinstance(recipient, str) or not recipient.strip():
            current_app.logger.warning(
                "Email skipped for %s: recipient is missing",
                context,
            )
            return False

        try:
            recipient = validate_email(
                recipient.strip(),
                check_deliverability=False,
            ).normalized
        except EmailNotValidError:
            current_app.logger.warning(
                "Email skipped for %s: recipient is invalid",
                context,
            )
            return False

        sender = current_app.config.get("RESEND_FROM")
        sender = sender.strip() if isinstance(sender, str) else ""

        if not sender or "\r" in sender or "\n" in sender:
            current_app.logger.warning(
                "Email skipped for %s: RESEND_FROM is missing or invalid",
                context,
            )
            return False

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
                "Email skipped for %s: use a production-authorized "
                "sender when test mode is disabled",
                context,
            )
            return False

    payload = {
        "from": sender,
        "to": [recipient],
        "subject": subject,
        "text": body,
    }

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "student-second-hand-marketplace/1.0",
            },
            json=payload,
            timeout=8,
        )

        if 200 <= response.status_code < 300:
            current_app.logger.info(
                "Resend accepted email request for %s (HTTP %s)",
                context,
                response.status_code,
            )
            return True

        try:
            error_data = response.json()
        except ValueError:
            error_data = {}

        error_name = (
            error_data.get("name")
            or error_data.get("type")
            or "unknown"
        )
        error_message = (
            error_data.get("message")
            or error_data.get("error")
            or "No JSON error detail returned"
        )

        current_app.logger.warning(
            "Resend rejected %s (HTTP %s, error=%s): %s",
            context,
            response.status_code,
            _sanitize_error(error_name, (api_key,)),
            _sanitize_error(error_message, (api_key, recipient)),
        )
        return False

    except requests.Timeout:
        current_app.logger.warning(
            "Resend request timed out for %s",
            context,
        )
        return False

    except requests.RequestException as error:
        current_app.logger.warning(
            "Resend request failed for %s (%s)",
            context,
            type(error).__name__,
        )
        return False


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
        "products.detail",
        product_id=product.id,
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
    created_at = getattr(user, "created_at", None)
    registration_date = (
        created_at.strftime("%Y-%m-%d %H:%M UTC")
        if created_at
        else "Not available"
    )

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

    admin_email = (
        current_app.config.get("ADMIN_NOTIFICATION_EMAIL")
        or current_app.config.get("SUPPORT_EMAIL")
        or current_app.config.get("MAIL_USERNAME")
    )

    return _send_email(
        admin_email,
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
