from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string


def send_welcome_email(user) -> None:
    html = render_to_string("emails/welcome.html", {"display_name": user.display_name})
    send_mail(
        subject="Welcome to Bible Golf",
        message=f"Welcome, {user.display_name}! Your account is ready.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        html_message=html,
        fail_silently=False,
    )


def send_password_reset_email(user, uid: str, token: str) -> None:
    reset_url = f"biblegolf://reset-password?uid={uid}&token={token}"
    html = render_to_string(
        "emails/password_reset.html",
        {"display_name": user.display_name, "reset_url": reset_url},
    )
    send_mail(
        subject="Reset your Bible Golf password",
        message=f"Reset your password: {reset_url}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        html_message=html,
        fail_silently=False,
    )
