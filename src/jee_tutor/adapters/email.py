"""Email adapter exports."""

from jee_tutor.email.delivery import EmailDeliveryCoordinator
from jee_tutor.email.ses_adapter import SesEmailSender

__all__ = ["EmailDeliveryCoordinator", "SesEmailSender"]
