package com.petros.ireview;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.*;

class ServerDiscoveryTest {

    private static Path legacyPath(Path home) {
        return home.resolve(".claude").resolve("interactive-review").resolve("server.json");
    }

    private static Path daemonConfigPath(Path home) {
        return home.resolve(".claude").resolve("webcompanion").resolve("config.json");
    }

    private static void write(Path file, String content) throws Exception {
        Files.createDirectories(file.getParent());
        Files.writeString(file, content);
    }

    @Test void resolvesFromDaemonConfigWhenPresent(@TempDir Path home) throws Exception {
        write(daemonConfigPath(home), "{\"port\": 3080, \"bind\": \"127.0.0.1\", \"token\": \"x\"}");

        String url = ServerDiscovery.resolve(home, legacyPath(home), "http://127.0.0.1:54620");

        assertEquals("http://127.0.0.1:3080", url);
    }

    @Test void defaultsBindTo127WhenAbsentFromDaemonConfig(@TempDir Path home) throws Exception {
        write(daemonConfigPath(home), "{\"port\": 3080, \"token\": \"x\"}");

        String url = ServerDiscovery.resolve(home, legacyPath(home), "http://127.0.0.1:54620");

        assertEquals("http://127.0.0.1:3080", url);
    }

    @Test void fallsBackToLegacyServerJsonWhenNoDaemonConfig(@TempDir Path home) throws Exception {
        write(legacyPath(home), "{\"type\": \"server-started\", \"url\": \"http://127.0.0.1:54621\"}");

        String url = ServerDiscovery.resolve(home, legacyPath(home), "http://127.0.0.1:54620");

        assertEquals("http://127.0.0.1:54621", url);
    }

    @Test void prefersDaemonConfigOverLegacyServerJsonWhenBothPresent(@TempDir Path home) throws Exception {
        write(daemonConfigPath(home), "{\"port\": 3080, \"bind\": \"127.0.0.1\"}");
        write(legacyPath(home), "{\"url\": \"http://127.0.0.1:54621\"}");

        String url = ServerDiscovery.resolve(home, legacyPath(home), "http://127.0.0.1:54620");

        assertEquals("http://127.0.0.1:3080", url);
    }

    @Test void fallsBackToDefaultWhenNeitherFileExists(@TempDir Path home) {
        String url = ServerDiscovery.resolve(home, legacyPath(home), "http://127.0.0.1:54620");

        assertEquals("http://127.0.0.1:54620", url);
    }

    @Test void fallsBackToDefaultWhenDaemonConfigIsMalformed(@TempDir Path home) throws Exception {
        write(daemonConfigPath(home), "not json");

        String url = ServerDiscovery.resolve(home, legacyPath(home), "http://127.0.0.1:54620");

        assertEquals("http://127.0.0.1:54620", url);
    }
}
