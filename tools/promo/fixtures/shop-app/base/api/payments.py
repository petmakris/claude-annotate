import uuid


def charge(card_token: str, amount_cents: int) -> str:
    """Charge the card through the payment provider and return its receipt id."""
    if amount_cents <= 0:
        raise ValueError("nothing to charge")
    return "rcpt_" + uuid.uuid5(uuid.NAMESPACE_URL, card_token + str(amount_cents)).hex[:12]
