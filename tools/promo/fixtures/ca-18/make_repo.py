"""make_repo.py <dest>: the invented `shop` repo the ca-18 IntelliJ clip opens.

It is the ca-13 shop (thirteen Gradle modules, four invented teams), plus real
code in checkout: RetryPolicy.java grows over three commits on main (the history
the smart diff key walks back), and the branch checkout-retry makes the checkout
flow retry a timed-out charge (the diff the ask-diff session shows). Every
commit is by Dana Example at a fixed date, so the shas are the same on every run.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = "checkout/src/main/java/com/acme/shop/checkout"

RETRY_1 = """package com.acme.shop.checkout.retry;

import java.time.Duration;

/** How a failed card charge is tried again. */
public final class RetryPolicy {

    private final int maxAttempts;

    public RetryPolicy(int maxAttempts) {
        this.maxAttempts = maxAttempts;
    }

    public boolean shouldRetry(int attempt, ChargeError error) {
        return attempt < maxAttempts;
    }

    public Duration delayBefore(int attempt) {
        return Duration.ZERO;
    }
}
"""

RETRY_2 = RETRY_1.replace("""        return Duration.ZERO;""", """        // 200 ms, 400 ms, 800 ms: the gateway asks for room after a timeout.
        return Duration.ofMillis(200L << (attempt - 1));""")

RETRY_3 = RETRY_2.replace("""        return attempt < maxAttempts;""", """        if (error == ChargeError.DECLINED) {
            return false;          // a declined card never succeeds on a retry
        }
        return attempt < maxAttempts;""")

CHARGE_ERROR = """package com.acme.shop.checkout.retry;

/** Why the payment gateway refused a charge. */
public enum ChargeError {
    TIMEOUT,
    DECLINED,
    GATEWAY_DOWN
}
"""

ORDER = """package com.acme.shop.checkout.flow;

/** An order ready to be paid. */
public record Order(String id, long total) {
}
"""

CHARGE_RESULT = """package com.acme.shop.checkout.payment;

import com.acme.shop.checkout.retry.ChargeError;

/** What the card gateway answered. */
public record ChargeResult(boolean ok, ChargeError error) {
}
"""

FLOW_MAIN = """package com.acme.shop.checkout.flow;

import com.acme.shop.checkout.payment.PaymentClient;
import com.acme.shop.checkout.payment.ChargeResult;

/** Places an order once the cart is paid. */
public final class FlowService {

    private final PaymentClient payments;

    public FlowService(PaymentClient payments) {
        this.payments = payments;
    }

    public ChargeResult pay(Order order) {
        return payments.charge(order.id(), order.total());
    }
}
"""

FLOW_BRANCH = """package com.acme.shop.checkout.flow;

import com.acme.shop.checkout.payment.PaymentClient;
import com.acme.shop.checkout.payment.ChargeResult;
import com.acme.shop.checkout.retry.RetryPolicy;

/** Places an order once the cart is paid. */
public final class FlowService {

    private final PaymentClient payments;
    private final RetryPolicy retry = new RetryPolicy(3);

    public FlowService(PaymentClient payments) {
        this.payments = payments;
    }

    public ChargeResult pay(Order order) {
        String key = "order-" + order.id();
        for (int attempt = 1; ; attempt++) {
            ChargeResult result = payments.charge(order.id(), order.total(), key);
            if (result.ok() || !retry.shouldRetry(attempt, result.error())) {
                return result;
            }
            sleep(retry.delayBefore(attempt));
        }
    }

    private static void sleep(java.time.Duration d) {
        try {
            Thread.sleep(d);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
"""

CLIENT_MAIN = """package com.acme.shop.checkout.payment;

/** Talks to the card gateway. */
public interface PaymentClient {

    ChargeResult charge(String orderId, long cents);
}
"""

CLIENT_BRANCH = """package com.acme.shop.checkout.payment;

/** Talks to the card gateway. */
public interface PaymentClient {

    /** The gateway charges one key once, so a retry never charges twice. */
    ChargeResult charge(String orderId, long cents, String idempotencyKey);
}
"""


def main():
    dest = Path(sys.argv[1])
    subprocess.run([sys.executable, str(HERE.parent / "ca-13" / "make_repo.py"), str(dest)],
                   check=True, stdout=subprocess.DEVNULL)
    day = iter(range(3, 28))

    def commit(msg, files):
        for rel, text in files.items():
            p = dest / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        d = f"2026-03-{next(day):02d}T10:00:00Z"
        env = dict(os.environ, GIT_AUTHOR_NAME="Dana Example", GIT_AUTHOR_EMAIL="dana@example.com",
                   GIT_COMMITTER_NAME="Dana Example", GIT_COMMITTER_EMAIL="dana@example.com",
                   GIT_AUTHOR_DATE=d, GIT_COMMITTER_DATE=d)
        git = lambda *a: subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=dest,
                                        env=env, check=True, stdout=subprocess.DEVNULL)
        git("add", "-A")
        git("commit", "-q", "-m", msg)
        return git

    commit("checkout: pay an order through the card gateway", {
        f"{PKG}/flow/FlowService.java": FLOW_MAIN,
        f"{PKG}/flow/Order.java": ORDER,
        f"{PKG}/payment/ChargeResult.java": CHARGE_RESULT,
        f"{PKG}/payment/PaymentClient.java": CLIENT_MAIN,
        f"{PKG}/retry/ChargeError.java": CHARGE_ERROR,
        f"{PKG}/retry/RetryPolicy.java": RETRY_1})
    commit("checkout: back off between charge retries", {f"{PKG}/retry/RetryPolicy.java": RETRY_2})
    git = commit("checkout: never retry a declined card", {f"{PKG}/retry/RetryPolicy.java": RETRY_3})
    git("remote", "add", "origin", "https://github.com/acme/shop.git")
    git("checkout", "-q", "-b", "checkout-retry")
    commit("checkout: retry a timed-out charge with one idempotency key", {
        f"{PKG}/flow/FlowService.java": FLOW_BRANCH,
        f"{PKG}/payment/PaymentClient.java": CLIENT_BRANCH})
    print(dest)


if __name__ == "__main__":
    main()
