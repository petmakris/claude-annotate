package com.petros.ireview;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Shared dual discovery for the ask_diff and walkthrough services'
 * base URL, tried in order:
 *
 * <ol>
 *   <li>the webcompanion daemon's own config, {@code ~/.claude/webcompanion/config.json}
 *       ({@code {"port": ..., "bind": ...}} — composed into a URL, since the file
 *       carries no {@code url} field of its own);</li>
 *   <li>the caller's legacy per-skill {@code server.json}, which still has a
 *       {@code url} field;</li>
 *   <li>the caller-supplied fallback, for when neither file exists yet.</li>
 * </ol>
 *
 * The daemon is tried first so that once a machine has it installed, both
 * services find it even before the legacy per-skill server.json is ever
 * written again. Kept until the five skills are cut over to the daemon and
 * the legacy discovery path is removed (see TODO.md "Plan 4").
 */
final class ServerDiscovery {

    private static final Pattern URL_FIELD = Pattern.compile("\"url\"\\s*:\\s*\"([^\"]+)\"");
    private static final Pattern PORT_FIELD = Pattern.compile("\"port\"\\s*:\\s*(\\d+)");
    private static final Pattern BIND_FIELD = Pattern.compile("\"bind\"\\s*:\\s*\"([^\"]+)\"");

    private ServerDiscovery() {}

    static String resolve(Path home, Path legacyServerJson, String fallbackUrl) {
        String daemon = readDaemonConfig(home.resolve(".claude").resolve("webcompanion").resolve("config.json"));
        if (daemon != null) return daemon;
        String legacy = readLegacyServerJson(legacyServerJson);
        if (legacy != null) return legacy;
        return fallbackUrl;
    }

    private static String readDaemonConfig(Path configJson) {
        try {
            String json = Files.readString(configJson);
            Matcher port = PORT_FIELD.matcher(json);
            if (!port.find()) return null;
            Matcher bind = BIND_FIELD.matcher(json);
            String host = bind.find() ? bind.group(1) : "127.0.0.1";
            return "http://" + host + ":" + port.group(1);
        } catch (IOException ignored) {
            return null;
        }
    }

    /** Package-visible so {@link ReviewSessionClient} can query the legacy
     *  server directly as a fallback when the daemon has no matching session
     *  for this skill — see the comment on {@code fetchNewestSession()}. */
    static String readLegacyServerJson(Path serverJson) {
        try {
            Matcher m = URL_FIELD.matcher(Files.readString(serverJson));
            if (m.find()) return m.group(1);
        } catch (IOException ignored) {
        }
        return null;
    }
}
