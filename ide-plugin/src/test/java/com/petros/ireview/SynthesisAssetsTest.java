package com.petros.ireview;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class SynthesisAssetsTest {

    @Test
    void highlighterScriptIsBundled() {
        String js = SynthesisAssets.highlighterScript();
        assertFalse(js.isEmpty(), "bundled highlight.js is missing from resources/web/");
        assertTrue(js.contains("Highlight.js"), "licence banner should be retained");
        assertTrue(js.contains("hljs"), js.substring(0, Math.min(200, js.length())));
    }

    @Test
    void highlighterScriptIsCachedNotReReadPerCall() {
        assertSame(SynthesisAssets.highlighterScript(), SynthesisAssets.highlighterScript());
    }

    @Test
    void bundleRegistersTheLanguagesTheSynthesisActuallyUses() {
        String js = SynthesisAssets.highlighterScript();
        for (String lang : new String[]{"java", "kotlin", "python", "yaml", "json", "xml", "bash", "sql"}) {
            assertTrue(js.contains("grmr_" + lang), "bundle is missing language: " + lang);
        }
    }

    @Test
    void scriptContainsNoClosingScriptTagThatWouldBreakInlining() {
        // The script is inlined inside <script>…</script>; a literal </script>
        // in the payload would terminate the block early and dump JS as text.
        assertFalse(SynthesisAssets.highlighterScript().contains("</script"),
                    "bundled JS must be safe to inline");
    }
}
