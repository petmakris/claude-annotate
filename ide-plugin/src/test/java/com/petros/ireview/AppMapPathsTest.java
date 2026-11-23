package com.petros.ireview;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/** The path matcher, on the cases file the Python side runs too. */
class AppMapPathsTest {

    private static JsonObject cases() throws Exception {
        return JsonParser.parseString(Files.readString(
            Path.of("../skills/app_map/tests/match_cases.json"))).getAsJsonObject();
    }

    @Test
    void everySharedCaseMatchesAsTheCasesFileSays() throws Exception {
        JsonArray all = cases().getAsJsonArray("cases");
        assertTrue(all.size() > 30, "the cases file should not be empty");
        for (JsonElement el : all) {
            JsonObject c = el.getAsJsonObject();
            String pattern = c.get("pattern").getAsString();
            String path = c.get("path").getAsString();
            assertEquals(c.get("match").getAsBoolean(), AppMapPaths.matches(pattern, path),
                "pattern '" + pattern + "' on '" + path + "'");
        }
    }

    @Test
    void theLastMatchingRuleWinsInEverySharedCase() throws Exception {
        JsonArray all = cases().getAsJsonArray("last_match_wins");
        assertFalse(all.isEmpty());
        for (JsonElement el : all) {
            JsonObject c = el.getAsJsonObject();
            List<String> rules = new ArrayList<>();
            c.getAsJsonArray("rules").forEach(r -> rules.add(r.getAsString()));
            int want = c.get("winner").isJsonNull() ? -1 : c.get("winner").getAsInt();
            assertEquals(want, AppMapPaths.lastMatch(rules, c.get("path").getAsString()),
                rules + " on " + c.get("path"));
        }
    }
}
