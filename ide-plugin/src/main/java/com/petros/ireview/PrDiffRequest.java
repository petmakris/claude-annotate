package com.petros.ireview;

import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

import java.util.Map;

/**
 * The parameters of a {@code jetbrains://idea/ireview/pr-diff?...} link, checked.
 * {@link PrDiffProtocolCommand} does the opening; this decides whether the link is one it can open.
 *
 * {@code number} must be a positive integer. {@code path}, {@code branch}, {@code repo} and
 * {@code id} are optional, and one that is blank is absent.
 */
record PrDiffRequest(long number, @Nullable String path, @Nullable String branch,
                     @Nullable String repo, @Nullable String id) {

    /** A request, or the message to hand back to the caller. Exactly one of them is set. */
    record Parsed(@Nullable PrDiffRequest request, @Nullable String error) {}

    static @NotNull Parsed parse(@Nullable String target, @NotNull Map<String, String> parameters) {
        if (!"pr-diff".equals(target)) {
            return new Parsed(null, "ireview: unknown command '" + target + "'");
        }
        Long number = positive(parameters.get("number"));
        if (number == null) {
            return new Parsed(null, "ireview pr-diff: missing or bad number '" + parameters.get("number") + "'");
        }
        return new Parsed(new PrDiffRequest(number, blankToNull(parameters.get("path")),
            blankToNull(parameters.get("branch")), blankToNull(parameters.get("repo")),
            blankToNull(parameters.get("id"))), null);
    }

    private static @Nullable Long positive(@Nullable String s) {
        if (s == null) return null;
        try {
            long n = Long.parseLong(s);
            return n > 0 ? n : null;
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static @Nullable String blankToNull(@Nullable String s) {
        return s == null || s.isBlank() ? null : s;
    }
}
