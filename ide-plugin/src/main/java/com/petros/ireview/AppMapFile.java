package com.petros.ireview;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParseException;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * A map.json written by /app-map: the drawings, the part rules and the owner
 * counts. Reads it and says where a repo-relative file sits. The format is
 * pinned by skills/app_map/tests/sample_map.json. No IntelliJ imports.
 */
public final class AppMapFile {

    public static final int VERSION = 1;

    /** The reason is the message; the overlay shows it as it is. */
    public static final class Unreadable extends Exception {
        public Unreadable(String reason) { super(reason); }
        public Unreadable(String reason, Throwable cause) { super(reason, cause); }
    }

    /** {@code part} is null when the file is on no part; {@code subPart} null when no detail part holds it. */
    public record Place(String part, String subPart, boolean hasDetail) {}

    public record Owner(String team, int files) {}

    /** A build module and its folder, repo-relative. */
    public record Module(String name, String dir, String repo) {}

    /** A team shown on a part: its short label, and the team (null for the files no CODEOWNERS rule covers). */
    public record Pill(String label, String team) {}

    /** A team gets a pill on a part when it owns at least this share of the part's files. */
    static final double PILL_SHARE = 0.2;
    static final int MAX_PILLS = 3;
    static final String NO_OWNER = "No owner";

    public static final class Run { public String text; public boolean mono; }

    /** One drawn shape. Fields not used by a kind stay at their defaults. */
    public static final class Shape {
        public String kind, role, tone, key, anchor;
        public double x, y, w, h, r, size, x1, y1, x2, y2;
        public int weight;
        public boolean dashed, arrow;
        public double[][] points;
        public List<Run> runs;
    }

    public static final class Drawing {
        public double width, height;
        public List<Shape> shapes = new ArrayList<>();
    }

    private static final class PartDef { String id; String repo; List<String> paths = new ArrayList<>(); }
    private static final class DetailDef { List<PartDef> parts = new ArrayList<>(); }
    private static final class Match { List<String> remotes = new ArrayList<>(); List<String> folders = new ArrayList<>(); }
    private static final class Built { String at; String commit; }
    private static final class Raw {
        int version;
        String name;
        Match match;
        Built built;
        List<PartDef> parts;
        Map<String, DetailDef> details;
        Map<String, List<Owner>> owners;
        Map<String, String> teams;
        List<Module> modules;
        Map<String, String> repos;
        Map<String, Drawing> drawings;
    }

    private final Raw raw;
    private final List<List<String>> partPaths = new ArrayList<>();
    private final Map<String, List<List<String>>> detailPaths = new LinkedHashMap<>();

    private AppMapFile(Raw raw) {
        this.raw = raw;
        for (PartDef p : raw.parts) partPaths.add(p.paths);
        for (var e : raw.details.entrySet()) {
            List<List<String>> l = new ArrayList<>();
            for (PartDef p : e.getValue().parts) l.add(p.paths);
            detailPaths.put(e.getKey(), l);
        }
    }

    public static AppMapFile read(Path mapJson) throws Unreadable {
        String text;
        try {
            text = Files.readString(mapJson);
        } catch (IOException e) {
            throw new Unreadable("cannot read " + mapJson.getFileName() + " (" + e.getMessage() + ")", e);
        }
        Raw raw;
        try {
            JsonObject root = JsonParser.parseString(text).getAsJsonObject();
            int version = root.has("version") && root.get("version").isJsonPrimitive()
                ? root.get("version").getAsInt() : -1;
            if (version != VERSION) {
                throw new Unreadable("map version " + version + " is not supported (this plugin reads version " + VERSION + ")");
            }
            raw = new Gson().fromJson(root, Raw.class);
        } catch (JsonParseException | IllegalStateException | NumberFormatException e) {
            throw new Unreadable("the file is not valid JSON of the map format (" + e.getMessage() + ")", e);
        }
        if (raw == null) throw new Unreadable("the file is empty");
        if (raw.parts == null) raw.parts = new ArrayList<>();
        if (raw.details == null) raw.details = new LinkedHashMap<>();
        if (raw.owners == null) raw.owners = new LinkedHashMap<>();
        if (raw.teams == null) raw.teams = new LinkedHashMap<>();
        if (raw.modules == null) raw.modules = new ArrayList<>();
        if (raw.repos == null) raw.repos = new LinkedHashMap<>();
        for (DetailDef d : raw.details.values()) if (d.parts == null) d.parts = new ArrayList<>();
        if (raw.match == null) raw.match = new Match();
        if (raw.drawings == null || raw.drawings.get("top") == null) throw new Unreadable("it has no top drawing");
        for (PartDef p : raw.parts) if (p.paths == null) p.paths = new ArrayList<>();
        for (DetailDef d : raw.details.values()) for (PartDef p : d.parts) if (p.paths == null) p.paths = new ArrayList<>();
        for (Drawing d : raw.drawings.values()) if (d.shapes == null) d.shapes = new ArrayList<>();
        return new AppMapFile(raw);
    }

    /** Just the {@code match} block of a map.json, for finding the map of a project; null when unreadable. */
    static List<List<String>> peekMatch(Path mapJson) {
        try {
            JsonObject root = JsonParser.parseString(Files.readString(mapJson)).getAsJsonObject();
            Match m = new Gson().fromJson(root.get("match"), Match.class);
            if (m == null) return null;
            return List.of(m.remotes == null ? List.of() : m.remotes, m.folders == null ? List.of() : m.folders);
        } catch (IOException | RuntimeException e) {
            return null;
        }
    }

    public String name() { return raw.name == null ? "" : raw.name; }

    public List<String> remotes() { return raw.match.remotes == null ? List.of() : raw.match.remotes; }

    public List<String> folders() { return raw.match.folders == null ? List.of() : raw.match.folders; }

    public String builtAt() { return raw.built == null || raw.built.at == null ? "" : raw.built.at; }

    public Set<String> detailIds() { return new LinkedHashSet<>(raw.details.keySet()); }

    /** "top" or a part id with a detail map; null when there is none. */
    public Drawing drawing(String id) { return raw.drawings.get(id); }

    public List<Owner> owners(String partId) {
        List<Owner> o = raw.owners.get(partId);
        return o == null ? List.of() : o;
    }

    /** Every part id with owner counts. */
    public Set<String> ownedIds() { return raw.owners.keySet(); }

    /** A team's short label: the map's own label, else the last part of its name in capitals. */
    public String label(String team) {
        String l = raw.teams.get(team);
        if (l != null && !l.isBlank()) return l;
        String t = team.startsWith("@") ? team.substring(1) : team;
        return t.substring(t.lastIndexOf('/') + 1).toUpperCase(java.util.Locale.ROOT);
    }

    /**
     * The teams to show on a part, biggest first: each team with at least {@link #PILL_SHARE} of its files, at most
     * {@link #MAX_PILLS}. A part where no team reaches that share gets one "No owner" pill. A part with no counts gets none.
     */
    public List<Pill> pills(String partId) {
        List<Owner> owners = owners(partId);
        int total = 0;
        for (Owner o : owners) total += o.files();
        if (total == 0) return List.of();
        List<Owner> big = new ArrayList<>();
        for (Owner o : owners) if (o.team() != null && o.files() >= PILL_SHARE * total) big.add(o);
        big.sort((a, b) -> b.files() != a.files() ? Integer.compare(b.files(), a.files()) : a.team().compareTo(b.team()));
        List<Pill> out = new ArrayList<>();
        for (Owner o : big) if (out.size() < MAX_PILLS) out.add(new Pill(label(o.team()), o.team()));
        if (out.isEmpty()) out.add(new Pill(NO_OWNER, null));
        return out;
    }

    /**
     * Which of the map's repos a checkout is, by its origin remote: the name of an extra repo the map lists, else null
     * for the map's own repo.
     */
    public String repoNameFor(String remote) {
        if (remote == null) return null;
        String want = AppMapStore.normaliseRemote(remote);
        for (var e : raw.repos.entrySet()) {
            if (e.getValue() != null && !e.getValue().isBlank() && AppMapStore.normaliseRemote(e.getValue()).equals(want)) return e.getKey();
        }
        return null;
    }

    public String module(String repoRelPath) { return module(repoRelPath, null); }

    /** The build module whose folder holds the file (the deepest one) in the given repo (null: the map's own), or null. */
    public String module(String repoRelPath, String repo) {
        String best = null;
        int bestLen = -1;
        for (Module m : raw.modules) {
            if (m == null || m.name() == null || m.dir() == null || !java.util.Objects.equals(m.repo(), repo)) continue;
            String dir = m.dir().replaceAll("/+$", "");
            boolean inside = dir.isEmpty() || dir.equals(".") || repoRelPath.startsWith(dir + "/");
            int len = dir.equals(".") ? 0 : dir.length();
            if (inside && len > bestLen) { best = m.name(); bestLen = len; }
        }
        return best;
    }

    /** Where a repo-relative file sits: the last part whose pattern matches, then the last detail part. */
    public Place place(String repoRelPath) { return place(repoRelPath, null); }

    /** As {@link #place(String)}, matching only the parts of the given repo (null: the map's own repo). */
    public Place place(String repoRelPath, String repo) {
        int top = -1;
        for (int i = raw.parts.size() - 1; i >= 0 && top < 0; i--) {
            if (!java.util.Objects.equals(raw.parts.get(i).repo, repo)) continue;
            for (String pattern : partPaths.get(i)) if (AppMapPaths.matches(pattern, repoRelPath)) { top = i; break; }
        }
        if (top < 0) return new Place(null, null, false);
        String part = raw.parts.get(top).id;
        List<List<String>> sub = detailPaths.get(part);
        if (sub == null) return new Place(part, null, false);
        int s = lastPart(sub, repoRelPath);
        return new Place(part, s < 0 ? null : raw.details.get(part).parts.get(s).id, true);
    }

    private static int lastPart(List<List<String>> parts, String path) {
        for (int i = parts.size() - 1; i >= 0; i--) {
            for (String pattern : parts.get(i)) {
                if (AppMapPaths.matches(pattern, path)) return i;
            }
        }
        return -1;
    }
}
