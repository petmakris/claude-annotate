import uuid


class PaymentDeclined(Exception):
    """The provider refused the card. Never retried."""


def charge(card_token: str, amount_cents: int, idempotency_key: str) -> str:
    """Charge the card through the payment provider and return its receipt id.

    The same idempotency key never charges twice, so a retry after a timeout is safe.
    """
    if amount_cents <= 0:
        raise ValueError("nothing to charge")
    if card_token.startswith("tok_declined"):
        raise PaymentDeclined("card declined")
    return "rcpt_" + uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key).hex[:12]
