from .cart import Cart
from .payments import charge


def checkout(cart: Cart, card_token: str) -> dict:
    if not cart.lines:
        raise ValueError("the cart is empty")
    amount = cart.total_cents()
    receipt = charge(card_token, amount)
    return {"status": "paid", "amount_cents": amount, "receipt": receipt}
