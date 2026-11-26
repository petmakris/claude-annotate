import time

from .payments import PaymentDeclined


def with_retry(call, attempts: int = 3, pause_s: float = 0.5):
    """Run `call`, trying again after a timeout. A declined card is not retried."""
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except PaymentDeclined:
            raise
        except TimeoutError:
            if attempt == attempts:
                raise
            time.sleep(pause_s * attempt)
