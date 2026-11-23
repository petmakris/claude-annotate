package com.petros.ireview;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/**
 * Web assets bundled into the plugin jar and inlined into the JCEF document.
 *
 * Bundled rather than fetched from a CDN: the popup must highlight code with no
 * network access, and a CDN load would also be a remote request from the user's
 * IDE on every answer.
 *
 * Read once and cached — {@link SynthesisHtmlRenderer#toDocument} runs on every
 * synthesis update, and re-reading 127KB from the jar each time is pure waste.
 * Pure: no IntelliJ dependencies, so it is unit-testable.
 */
public final class SynthesisAssets {

    private static final String HIGHLIGHTER = read("/web/highlight.min.js");

    /** Highlight.js (BSD-3-Clause), "common" build — see resources/web/README.md. */
    public static String highlighterScript() {
        return HIGHLIGHTER;
    }

    private static String read(String resource) {
        try (InputStream in = SynthesisAssets.class.getResourceAsStream(resource)) {
            if (in == null) return "";
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            // A missing asset degrades the popup to unhighlighted code; it must
            // never take the popup down with it.
            return "";
        }
    }

    private SynthesisAssets() {}
}
