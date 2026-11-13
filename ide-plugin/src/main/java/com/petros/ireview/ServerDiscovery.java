package com.petros.ireview;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Resolves the base URL of the webcompanion daemon that both the ask_diff and
 * the walkthrough clients talk to, from the daemon's own config,
 * {@code ~/.claude/webcompanion/config.json} ({@code {"port": ..., "bind": ...}}
 * — composed into a URL, since the file carries no {@code url} field of its
 * own). A missing or unreadable file, or one without a port, resolves to the
 * daemon's own defaults, {@link #DEFAULT_URL}.
 */
final class ServerDiscovery {

    /** The daemon's defaults: {@code DEFAULT_BIND} and {@code DEFAULT_PORT} in
     *  webcompanion's {@code config.py}. */
    static final String DEFAULT_HOST = "127.0.0.1";
    static final int DEFAULT_PORT = 3080;
    static final String DEFAULT_URL = "http://" + DEFAULT_HOST + ":" + DEFAULT_PORT;

    private static final Pattern PORT_FIELD = Pattern.compile("\"port\"\\s*:\\s*(\\d{1,5})\\b");
    private static final Pattern BIND_FIELD = Pattern.compile("\"bind\"\\s*:\\s*\"([^\"]+)\"");

    private ServerDiscovery() {}

    static String resolve(Path home) {
        Path configJson = home.resolve(".claude").resolve("webcompanion").resolve("config.json");
        String json;
        try {
            json = Files.readString(configJson);
        } catch (NoSuchFileException e) {
            // Not configured yet: the daemon itself runs on its defaults then.
            return DEFAULT_URL;
        } catch (IOException e) {
            // Unreadable right now (permissions, a write in progress). The
            // clients re-resolve after every failed poll, so the next one
            // tries the file again; until then aim at the default.
            return DEFAULT_URL;
        }
        Matcher port = PORT_FIELD.matcher(json);
        int portNumber = port.find() ? Integer.parseInt(port.group(1)) : DEFAULT_PORT;
        Matcher bind = BIND_FIELD.matcher(json);
        String host = bind.find() ? connectHost(bind.group(1)) : DEFAULT_HOST;
        return "http://" + host + ":" + portNumber;
    }

    /** {@code bind} is where the daemon listens, which may be a wildcard; a
     *  client cannot connect to a wildcard on every OS, so it uses loopback. */
    private static String connectHost(String bind) {
        return switch (bind) {
            case "0.0.0.0", "::", "[::]", "" -> DEFAULT_HOST;
            default -> bind;
        };
    }
}
