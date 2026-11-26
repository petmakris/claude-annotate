from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Invoice:
    id: str
    customer_id: str
    amount: Decimal          # euros, two decimals
    currency: str = "EUR"

    def amount_cents(self) -> int:
        return int(self.amount * 100)
