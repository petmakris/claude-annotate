package com.petros.ireview;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import static com.petros.ireview.WebCompanionHttp.str;

/**
 * A parsed walkthrough document (the {@code __steps__} item's body). Parsing
 * is total: malformed input yields {@link #EMPTY} and individual malformed
 * steps are skipped, so a bad document degrades the tour instead of breaking
 * the IDE.
 */
public record WalkthroughDoc(String question, String kind, long generatedTs,
                             List<WalkthroughStep> steps) {

    public static final WalkthroughDoc EMPTY =
        new WalkthroughDoc("", "", 0L, List.of());

    public WalkthroughDoc {
        steps = Collections.unmodifiableList(new ArrayList<>(steps));
    }

    public boolean isEmpty() { return steps.isEmpty(); }

    public static WalkthroughDoc parse(String json) {
        if (json == null || json.isBlank()) return EMPTY;
        JsonObject root;
        try {
            JsonElement parsed = JsonParser.parseString(json);
            if (!parsed.isJsonObject()) return EMPTY;
            root = parsed.getAsJsonObject();
        } catch (Exception e) {
            return EMPTY;
        }
        JsonElement stepsEl = root.get("steps");
        if (stepsEl == null || !stepsEl.isJsonArray()) return EMPTY;
        List<WalkthroughStep> steps = new ArrayList<>();
        for (JsonElement el : stepsEl.getAsJsonArray()) {
            WalkthroughStep step = parseStep(el);
            if (step != null) steps.add(step);
        }
        if (steps.isEmpty()) return EMPTY;
        return new WalkthroughDoc(str(root, "question"), str(root, "kind"),
            num(root, "generated_ts"), steps);
    }

    private static WalkthroughStep parseStep(JsonElement el) {
        if (el == null || !el.isJsonObject()) return null;
        JsonObject o = el.getAsJsonObject();
        int id = (int) num(o, "id");
        int line = (int) num(o, "line");
        String file = str(o, "file");
        String snippet = str(o, "snippet");
        if (id < 1 || line < 1 || file.isEmpty() || snippet.isEmpty()) return null;
        return new WalkthroughStep(id, str(o, "title"), file, line, snippet,
            WalkthroughStep.Role.from(str(o, "role")), str(o, "markdown"));
    }

    private static long num(JsonObject o, String key) {
        JsonElement v = o.get(key);
        if (v == null || v.isJsonNull() || !v.isJsonPrimitive()) return 0L;
        try {
            return v.getAsLong();
        } catch (NumberFormatException e) {
            return 0L;
        }
    }
}
