import smtplib
from urllib.parse import urljoin

from email_validator import EmailNotValidError, validate_email
from flask import current_app, url_for
from flask_mail import Message

from .extensions import mail


def _absolute_url(endpoint, **values):
    base_url = current_app.config["PUBLIC_BASE_URL"].rstrip("/") + "/"
    return urljoin(base_url, url_for(endpoint, **values).lstrip("/"))


def _send_listing_email(product_id, recipient, subject, body):
    if not recipient:
        current_app.logger.warning(
            "Listing email notification was skipped for product id %s: no recipient configured",
            product_id,
        )
        return False

    try:
        mail.send(Message(subject=subject, recipients=[recipient], body=body))
    except smtplib.SMTPServerDisconnected:
        current_app.logger.warning(
            "Listing email notification failed for product id %s: SMTP server disconnected; "
            "verify SMTP connectivity, TLS/port settings, and Gmail App Password configuration",
            product_id,
        )
        return False
    except (OSError, RuntimeError, smtplib.SMTPException, ValueError) as error:
        current_app.logger.warning(
            "Listing email notification failed for product id %s (%s)",
            product_id,
            type(error).__name__,
        )
        return False
    return True


def notify_admin_listing_submitted(product):
    admin_email = current_app.config.get("MAIL_USERNAME")
    category_name = product.category.name if product.category else "Not specified"
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
    listing_url = _absolute_url("products.detail", product_id=product.id)
    body = (
        f"Your listing, “{product.title}”, was {approval_status} by an administrator.\n\n"
        f"View your listing: {listing_url}\n"
    )
    return _send_listing_email(
        product.id,
        seller_email,
        f"Your listing was {approval_status}",
        body,
    )


def notify_account_suspended(user):
    support_email = current_app.config.get("SUPPORT_EMAIL")
    if not support_email:
        current_app.logger.warning(
            "Account suspension email was skipped for user id %s: SUPPORT_EMAIL and MAIL_USERNAME are not configured",
            user.id,
        )
        return False

    body = (
        f"Hello {user.name},\n\n"
        "Your Student Second-Hand Marketplace account has been suspended by the administrator.\n\n"
        "You may be unable to access marketplace features while your account is suspended. "
        "If you believe this decision was made in error or would like further clarification, "
        "you may request a review by contacting support:\n\n"
        f"{support_email}\n\n"
        "Please include your registered email address and explain your concern. "
        "Do not send your password or other authentication credentials.\n\n"
        "Regards,\n"
        "Student Second-Hand Marketplace Support Team\n"
    )
    try:
        mail.send(
            Message(
                subject="Important: Your marketplace account has been suspended",
                recipients=[user.university_email],
                body=body,
            )
        )
    except (OSError, RuntimeError, smtplib.SMTPException, ValueError) as error:
        current_app.logger.warning(
            "Account suspension email failed for user id %s (%s)",
            user.id,
            type(error).__name__,
        )
        return False
    return True


def notify_student_account_activated(user):
    recipient = user.university_email
    try:
        if not isinstance(recipient, str) or not recipient.strip():
            raise EmailNotValidError("No email address was provided.")
        recipient = validate_email(
            recipient.strip(), check_deliverability=False
        ).normalized
    except EmailNotValidError:
        current_app.logger.warning(
            "Account reactivation email was skipped for user id %s: no valid recipient",
            user.id,
        )
        return False

    student_name = " ".join((user.name or "").split()) or "there"
    support_email = current_app.config.get("SUPPORT_EMAIL")
    support_paragraph = (
        "\nIf you have any questions or need assistance, please contact our "
        f"support team at:\n\n{support_email}\n"
        if support_email
        else ""
    )
    body = (
        f"Hello {student_name},\n\n"
        "Good news! Your Student Second-Hand Marketplace account has been "
        "reactivated by the administrator.\n\n"
        "You can now log in again and access the marketplace features available "
        "to your account.\n"
        f"{support_paragraph}\n"
        "Thank you for being part of the Student Second-Hand Marketplace.\n\n"
        "Regards,\n"
        "Student Second-Hand Marketplace Support Team\n"
    )
    try:
        mail.send(
            Message(
                subject="Your Student Second-Hand Marketplace Account Has Been Reactivated",
                recipients=[recipient],
                body=body,
                sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
            )
        )
    except (OSError, RuntimeError, smtplib.SMTPException, ValueError) as error:
        current_app.logger.warning(
            "Account reactivation email failed for user id %s (%s)",
            user.id,
            type(error).__name__,
        )
        return False
    return True
