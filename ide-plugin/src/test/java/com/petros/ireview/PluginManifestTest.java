package com.petros.ireview;

import org.junit.jupiter.api.Test;
import java.nio.file.Files;
import java.nio.file.Path;
import static org.junit.jupiter.api.Assertions.*;

/**
 * Structural guards on META-INF/plugin.xml — the half of a platform dependency
 * that no compile step checks. Compiling against a class only proves the jar
 * was on the compile classpath; whether the class is visible at RUNTIME is
 * decided entirely by what plugin.xml asks for.
 */
class PluginManifestTest {

    private static final Path META = Path.of("src/main/resources/META-INF");

    private static String manifest() throws Exception {
        return Files.readString(META.resolve("plugin.xml"));
    }

    @Test
    void declaresTheJcefDependencyItCompilesAgainst() throws Exception {
        // The regression: com.intellij.ui.jcef moved out of
        // com.intellij.modules.platform and into its own bundled plugin at
        // build 262. The code kept compiling; every panel-row click then threw
        // NoClassDefFoundError on the EDT, because nothing asked the platform
        // to put that plugin on this plugin's classloader.
        String xml = manifest();
        assertTrue(xml.contains("com.intellij.modules.jcef"),
            "SynthesisPopup calls JBCefApp — plugin.xml must depend on com.intellij.modules.jcef");
        assertTrue(xml.contains("optional=\"true\" config-file=\"jcef.xml\""),
            "the dependency must be optional: SynthesisPopup falls back to a JEditorPane without it");
        assertTrue(Files.exists(META.resolve("jcef.xml")),
            "an optional depends names a config file that has to exist, or the plugin fails to load");
    }

    @Test
    void everyDeclaredConfigFileExists() throws Exception {
        var m = java.util.regex.Pattern.compile("config-file=\"([^\"]+)\"").matcher(manifest());
        int seen = 0;
        while (m.find()) {
            seen++;
            assertTrue(Files.exists(META.resolve(m.group(1))),
                "plugin.xml names config-file " + m.group(1) + " but it is not in META-INF");
        }
        assertTrue(seen > 0, "expected at least the jcef optional-depends config file");
    }
}
