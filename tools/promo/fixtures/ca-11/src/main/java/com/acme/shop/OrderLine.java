package com.acme.shop;

import lombok.Data;
import lombok.NonNull;

/** One product in the order. */
@Data
public class OrderLine {
    @NonNull private String sku;
    private int quantity;
    private long priceCents;
}
