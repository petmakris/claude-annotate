package com.petros.ireview;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpRequest;
import java.nio.charset.StandardCharsets;

/** Shared constants/helpers for every Java client speaking the webcompanion daemon's wire protocol. */
final class WebCompanionHttp {

    static final String CONTRACT_VERSION = "1";

    private WebCompanionHttp() {}

    /** Stamps the daemon's contract-version header on a request builder, returning it for chaining. */
    static HttpRequest.Builder withContract(HttpRequest.Builder builder) {
        return builder.header("X-WebCompanion-Contract", CONTRACT_VERSION);
    }

    /** {@code GET /api/sessions?kind=<kind>&cwd=<cwd>}: the sessions of one kind for one project. */
    static URI sessionsUri(String baseUrl, String kind, String cwd) {
        return URI.create(baseUrl + "/api/sessions?kind=" + encode(kind) + "&cwd=" + encode(cwd));
    }

    /**
     * {@code /s/<sid>/<route>?kind=<kind>} — every per-session route is
     * kind-scoped on the daemon. {@code route} is the path below the session,
     * e.g. {@code poll}, {@code items}, {@code threads}, {@code stream},
     * {@code api/submit}, {@code api/cancel}, {@code api/threads/delete}.
     */
    static URI sessionUri(String baseUrl, String sid, String route, String kind) {
        return URI.create(baseUrl + "/s/" + sid + "/" + route + "?kind=" + encode(kind));
    }

    /** Null-safe string field read; "" when absent, null, or not a primitive. */
    static String str(JsonObject o, String key) {
        JsonElement v = o.get(key);
        return (v == null || !v.isJsonPrimitive()) ? "" : v.getAsString();
    }

    /** Numeric field read; {@code fallback} when absent, null, or not a number. */
    static long num(JsonObject o, String key, long fallback) {
        JsonElement v = o.get(key);
        if (v == null || !v.isJsonPrimitive() || !v.getAsJsonPrimitive().isNumber()) return fallback;
        return v.getAsLong();
    }

    /** Boolean field read; false when absent, null, or not a boolean. */
    static boolean flag(JsonObject o, String key) {
        JsonElement v = o.get(key);
        return v != null && v.isJsonPrimitive() && v.getAsJsonPrimitive().isBoolean() && v.getAsBoolean();
    }

    private static String encode(String s) {
        return URLEncoder.encode(s, StandardCharsets.UTF_8);
    }
}
