package com.petros.ireview;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Which parts a mode of the app map lights, and how: the open file's part, the parts a branch changes, the parts of
 * the open tabs (darker with more tabs), the parts that use the open file, and the steps of a walkthrough. Works on
 * {@link AppMapFile.Place}s, so it has no IntelliJ imports. No mode shows a number of files (the user's rule).
 */
public final class AppMapLights {

    private AppMapLights() {}

    public enum Kind {
        /** The open file's part, or the current walkthrough step's. */
        HERE,
        /** A part the branch changes. */
        CHANGED,
        /** A part with open tabs; {@link Mark#heat} says how many, from just above 0 to 1. */
        HEAT,
        /** A part that uses the open file. */
        USER,
        /** A walkthrough step before or after the current one. */
        STEP
    }

    /** How one part is lit. {@code number} is a walkthrough step's number, else null. */
    public record Mark(Kind kind, double heat, String number) {
        static Mark of(Kind k) { return new Mark(k, 1, null); }
    }

    /** The id a place has on the drawing in front: its top part, or on a detail map its sub-part there. */
    static String idOn(AppMapFile.Place p, String detailId) {
        if (p == null || p.part() == null) return null;
        if (detailId == null) return p.part();
        return detailId.equals(p.part()) ? p.subPart() : null;
    }

    public static Map<String, Mark> here(AppMapFile.Place p, String detailId) {
        Map<String, Mark> out = new LinkedHashMap<>();
        String id = idOn(p, detailId);
        if (id != null) out.put(id, Mark.of(Kind.HERE));
        return out;
    }

    public static Map<String, Mark> changed(List<AppMapFile.Place> places, String detailId) {
        Map<String, Mark> out = new LinkedHashMap<>();
        for (AppMapFile.Place p : places) {
            String id = idOn(p, detailId);
            if (id != null) out.put(id, Mark.of(Kind.CHANGED));
        }
        return out;
    }

    /** Heat runs from {@link #MIN_HEAT} for the part with the fewest tabs to 1 for the one with the most. */
    static final double MIN_HEAT = 0.25;

    public static Map<String, Mark> tabs(List<AppMapFile.Place> places, String detailId) {
        Map<String, Integer> count = new LinkedHashMap<>();
        for (AppMapFile.Place p : places) {
            String id = idOn(p, detailId);
            if (id != null) count.merge(id, 1, Integer::sum);
        }
        int max = 0;
        for (int n : count.values()) max = Math.max(max, n);
        Map<String, Mark> out = new LinkedHashMap<>();
        for (var e : count.entrySet()) {
            double heat = max <= 1 ? 1 : MIN_HEAT + (1 - MIN_HEAT) * (e.getValue() - 1) / (double) (max - 1);
            out.put(e.getKey(), new Mark(Kind.HEAT, heat, null));
        }
        return out;
    }

    /** The open file's part, and every other part holding a file that uses it. */
    public static Map<String, Mark> users(AppMapFile.Place here, List<AppMapFile.Place> users, String detailId) {
        Map<String, Mark> out = here(here, detailId);
        for (AppMapFile.Place p : users) {
            String id = idOn(p, detailId);
            if (id != null && !out.containsKey(id)) out.put(id, Mark.of(Kind.USER));
        }
        return out;
    }

    /**
     * The walkthrough's steps in order: each part a step lands on carries the number of its first step, and the
     * current step's part is lit with the current step's number. {@code current} is 0-based.
     */
    public static Map<String, Mark> steps(List<AppMapFile.Place> steps, int current, String detailId) {
        Map<String, Mark> out = new LinkedHashMap<>();
        for (int i = 0; i < steps.size(); i++) {
            String id = idOn(steps.get(i), detailId);
            if (id != null && !out.containsKey(id)) out.put(id, new Mark(Kind.STEP, 1, String.valueOf(i + 1)));
        }
        if (current >= 0 && current < steps.size()) {
            String id = idOn(steps.get(current), detailId);
            if (id != null) out.put(id, new Mark(Kind.HERE, 1, String.valueOf(current + 1)));
        }
        return out;
    }

    /** The parts the steps visit, in the order of the steps, each once: the trail the map draws between them. */
    public static List<String> trail(List<AppMapFile.Place> steps, String detailId) {
        List<String> out = new ArrayList<>();
        for (AppMapFile.Place p : steps) {
            String id = idOn(p, detailId);
            if (id != null && (out.isEmpty() || !Objects.equals(out.get(out.size() - 1), id)) && !out.contains(id)) out.add(id);
        }
        return out;
    }
}
