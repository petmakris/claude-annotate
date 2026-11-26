package com.acme.shop;

import lombok.Data;
import lombok.NonNull;
import org.jspecify.annotations.Nullable;

/** Who placed the order. A guest has no account. */
@Data
public class Customer {
    @Nullable private String accountId;
    @NonNull private String email;
    private boolean guest;
}
