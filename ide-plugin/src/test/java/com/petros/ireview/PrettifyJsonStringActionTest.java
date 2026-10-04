package com.petros.ireview;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class PrettifyJsonStringActionTest {

    /**
     * What javac makes of a text block literal, per JLS 3.10.6: the content
     * between the opening delimiter's line terminator and the closing
     * delimiter, with incidental whitespace stripped and escapes interpreted.
     */
    private static String javacValueOf(String textBlockSource) {
        assertTrue(textBlockSource.startsWith("\"\"\"\n"), textBlockSource);
        assertTrue(textBlockSource.endsWith("\"\"\""), textBlockSource);
        String content = textBlockSource.substring(4, textBlockSource.length() - 3);
        return content.stripIndent().translateEscapes();
    }

    /** The formatted JSON, run through the action's text block builder and back
     *  through javac's reading of it, must come out unchanged. */
    private static void assertRoundTrips(String json) {
        String formatted = JsonStringPrettifier.prettify(json).orElseThrow();
        String block = PrettifyJsonStringAction.buildTextBlock(formatted, "        ");
        assertEquals(formatted + "\n", javacValueOf(block), block);
    }

    @Test void escapedNewlineInAJsonStringKeepsItsBackslash() {
        // The text block's value holds the JSON escape \n (backslash, n).
        // Written back raw, javac reads it as a real newline and the string
        // the code holds changes.
        assertRoundTrips("{\"a\":\"x\\ny\"}");
    }

    @Test void escapedQuotesAndBackslashesSurvive() {
        assertRoundTrips("{\"path\":\"C:\\\\tmp\\\\x\",\"q\":\"say \\\"hi\\\"\"}");
    }

    @Test void unicodeEscapeStaysAnEscape() {
        assertRoundTrips("{\"u\":\"\\u0041\\t\"}");
    }

    @Test void placeholdersStillRoundTrip() {
        assertRoundTrips("{ \"assetId\": \"{{assetId}}\", \"n\": {{count}} }");
    }

    @Test void tripleQuoteNeverClosesTheBlockEarly() {
        String raw = "{\"a\": \"\"\"\"\"}";
        String block = PrettifyJsonStringAction.buildTextBlock(raw, "");
        assertEquals(raw + "\n", javacValueOf(block));
        assertNoUnescapedTripleQuote(block.substring(4, block.length() - 3));
    }

    /** Lexes the body as javac does — a backslash escapes the next character —
     *  and fails on three raw quotes in a row, which would close the block. */
    private static void assertNoUnescapedTripleQuote(String body) {
        int run = 0;
        for (int i = 0; i < body.length(); i++) {
            char c = body.charAt(i);
            if (c == '\\') {
                i++;
                run = 0;
            } else if (c == '"') {
                run++;
                assertTrue(run < 3, "an unescaped \"\"\" would end the text block early: " + body);
            } else {
                run = 0;
            }
        }
    }
}
