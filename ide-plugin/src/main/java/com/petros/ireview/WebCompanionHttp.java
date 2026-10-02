package com.petros.ireview;

import java.net.http.HttpRequest;

/** Shared constants/helpers for every Java client speaking the webcompanion daemon's wire protocol. */
final class WebCompanionHttp {

    static final String CONTRACT_VERSION = "1";

    private WebCompanionHttp() {}

    /** Stamps the daemon's contract-version header on a request builder, returning it for chaining. */
    static HttpRequest.Builder withContract(HttpRequest.Builder builder) {
        return builder.header("X-WebCompanion-Contract", CONTRACT_VERSION);
    }
}
