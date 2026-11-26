from .cart import Cart
from .payments import charge, PaymentDeclined
from .retry import with_retry


def checkout(cart: Cart, card_token: str, idempotency_key: str) -> dict:
    if not cart.lines:
        raise ValueError("the cart is empty")
    amount = cart.total_cents()
    try:
        receipt = with_retry(lambda: charge(card_token, amount, idempotency_key))
    except PaymentDeclined as e:
        return {"status": "declined", "reason": str(e)}
    return {"status": "paid", "amount_cents": amount, "receipt": receipt}
