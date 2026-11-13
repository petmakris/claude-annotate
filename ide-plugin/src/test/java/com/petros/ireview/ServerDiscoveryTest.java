package com.petros.ireview;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.*;

class ServerDiscoveryTest {

    private static Path daemonConfigPath(Path home) {
        return home.resolve(".claude").resolve("webcompanion").resolve("config.json");
    }

    private static void write(Path file, String content) throws Exception {
        Files.createDirectories(file.getParent());
        Files.writeString(file, content);
    }

    @Test void resolvesFromDaemonConfigWhenPresent(@TempDir Path home) throws Exception {
        write(daemonConfigPath(home), "{\"port\": 3091, \"bind\": \"127.0.0.2\", \"token\": \"x\"}");

        assertEquals("http://127.0.0.2:3091", ServerDiscovery.resolve(home));
    }

    @Test void defaultsBindTo127WhenAbsentFromDaemonConfig(@TempDir Path home) throws Exception {
        write(daemonConfigPath(home), "{\"port\": 3091, \"token\": \"x\"}");

        assertEquals("http://127.0.0.1:3091", ServerDiscovery.resolve(home));
    }

    @Test void aWildcardBindConnectsOverLoopback(@TempDir Path home) throws Exception {
        write(daemonConfigPath(home), "{\"port\": 3080, \"bind\": \"0.0.0.0\"}");

        assertEquals("http://127.0.0.1:3080", ServerDiscovery.resolve(home));
    }

    @Test void defaultsPortTo3080WhenAbsentFromDaemonConfig(@TempDir Path home) throws Exception {
        write(daemonConfigPath(home), "{\"bind\": \"127.0.0.1\", \"token\": \"x\"}");

        assertEquals("http://127.0.0.1:3080", ServerDiscovery.resolve(home));
    }

    @Test void fallsBackToTheDaemonDefaultWhenNoConfigExists(@TempDir Path home) {
        assertEquals("http://127.0.0.1:3080", ServerDiscovery.resolve(home));
    }

    @Test void ignoresTheRetiredPerSkillServerJson(@TempDir Path home) throws Exception {
        write(home.resolve(".claude").resolve("interactive-review").resolve("server.json"),
            "{\"url\": \"http://127.0.0.1:54621\"}");

        assertEquals("http://127.0.0.1:3080", ServerDiscovery.resolve(home));
    }

    @Test void fallsBackToTheDaemonDefaultWhenConfigIsMalformed(@TempDir Path home) throws Exception {
        write(daemonConfigPath(home), "not json");

        assertEquals("http://127.0.0.1:3080", ServerDiscovery.resolve(home));
    }

    @Test void anOverlongPortIsIgnoredRatherThanThrown(@TempDir Path home) throws Exception {
        write(daemonConfigPath(home), "{\"port\": 99999999999}");

        assertEquals("http://127.0.0.1:3080", ServerDiscovery.resolve(home));
    }
}
