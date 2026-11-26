package com.acme.shop;

import java.util.List;
import lombok.Data;
import lombok.NonNull;
import org.jspecify.annotations.Nullable;
import com.acme.payments.PaymentMethod;

/** One order placed in the shop. */
@Data
public class Order {
    @NonNull private String id;
    @NonNull private Customer customer;
    @NonNull private List<OrderLine> lines;
    private long totalCents;
    @NonNull private PaymentMethod payment;
    /** Set only when a signed-in customer redeems a code at checkout. */
    @Nullable private String discountCode;
}
