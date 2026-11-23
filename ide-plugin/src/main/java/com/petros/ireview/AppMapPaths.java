package com.petros.ireview;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Pattern;

/**
 * The path matcher of the app map: GitHub's CODEOWNERS rules, used for a map's
 * parts and for the CODEOWNERS file itself. The Python build has a twin
 * (skills/app_map/paths.py); both run skills/app_map/tests/match_cases.json.
 *
 * No IntelliJ imports.
 */
public final class AppMapPaths {

    private AppMapPaths() {}

    private static final Map<String, Pattern> CACHE = new ConcurrentHashMap<>();

    /** Whether the repo-relative file {@code path} (no leading slash) is covered by {@code pattern}. */
    public static boolean matches(String pattern, String path) {
        return CACHE.computeIfAbsent(pattern, AppMapPaths::compile).matcher(path).matches();
    }

    /** Index of the last rule that matches {@code path}, or -1: the last rule wins, as in CODEOWNERS. */
    public static int lastMatch(List<String> rules, String path) {
        for (int i = rules.size() - 1; i >= 0; i--) {
            if (matches(rules.get(i), path)) return i;
        }
        return -1;
    }

    private static Pattern compile(String raw) {
        String p = raw.trim();
        boolean anchored = p.startsWith("/") || p.indexOf('/') >= 0 && p.indexOf('/') < p.length() - 1;
        if (p.startsWith("/")) p = p.substring(1);
        boolean folder = p.endsWith("/");
        if (folder) p = p.substring(0, p.length() - 1);
        // A last segment of exactly "*" names the files of that folder, no deeper.
        boolean noDeeper = p.equals("*") || p.endsWith("/*");

        StringBuilder re = new StringBuilder(anchored ? "^" : "^(?:.*/)?");
        for (int i = 0; i < p.length(); i++) {
            char c = p.charAt(i);
            if (c == '*' && i + 1 < p.length() && p.charAt(i + 1) == '*') {
                boolean slashAfter = i + 2 < p.length() && p.charAt(i + 2) == '/';
                if (slashAfter) { re.append("(?:.*/)?"); i += 2; }
                else { re.append(".*"); i += 1; }
            } else if (c == '*') {
                re.append("[^/]*");
            } else if (c == '?') {
                re.append("[^/]");
            } else {
                re.append(Pattern.quote(String.valueOf(c)));
            }
        }
        if (folder) re.append("/.+");
        else if (!noDeeper && !p.endsWith("/**") && !p.equals("**")) re.append("(?:/.*)?");
        re.append("$");
        return Pattern.compile(re.toString());
    }
}
