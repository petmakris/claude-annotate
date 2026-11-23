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
    void declaresTheGitDependencyTheDiffActionsNeed() throws Exception {
        // Same class of regression as the JCEF one above: git4idea currently
        // reaches this plugin only transitively, through the GitHub plugin's
        // own dependencies. Compiling proves nothing about runtime visibility,
        // and the GitHub plugin dropping that edge would break the diff actions
        // with NoClassDefFoundError and no compile warning.
        assertTrue(manifest().contains("<depends>Git4Idea</depends>"),
            "SmartDiffService calls git4idea — plugin.xml must depend on Git4Idea directly");
        assertTrue(Files.readString(Path.of("build.gradle.kts")).contains("bundledPlugin(\"Git4Idea\")"),
            "the manifest depends on Git4Idea, so the build must put it on the compile classpath");
    }

    @Test
    void everyActionRegisteredInTheManifestAppearsInTheShortcutsPanel() throws Exception {
        // A registered action absent from the catalog is a key the user can
        // press but cannot discover; the panel is the only place we advertise
        // these, so drift between the two is silent.
        var m = java.util.regex.Pattern
            .compile("<action id=\"(com\\.petros\\.ireview\\.[^\"]+)\"").matcher(manifest());
        var listed = ShortcutCatalog.rows().stream().map(ShortcutCatalog.Row::actionId).toList();
        int seen = 0;
        while (m.find()) {
            seen++;
            assertTrue(listed.contains(m.group(1)),
                "plugin.xml registers " + m.group(1) + " but ShortcutCatalog does not list it");
        }
        assertTrue(seen > 0, "expected the manifest to register this plugin's actions");
    }

    @Test
    void everyPluginActionInTheShortcutsPanelIsActuallyRegistered() throws Exception {
        // The other direction: a catalog row naming an id nothing registers
        // renders forever as "unassigned", which reads as a keymap problem
        // rather than the typo it is.
        String xml = manifest();
        for (var row : ShortcutCatalog.rows()) {
            if (!row.actionId().startsWith("com.petros.ireview.")) continue;
            assertTrue(xml.contains("<action id=\"" + row.actionId() + "\""),
                "ShortcutCatalog lists " + row.actionId() + " but plugin.xml does not register it");
        }
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

    /** Every {@code <keyboard-shortcut>} this plugin declares, as (keymap, keystroke, action). */
    private static java.util.List<String[]> declaredShortcuts() throws Exception {
        var out = new java.util.ArrayList<String[]>();
        var action = java.util.regex.Pattern
            .compile("<action id=\"(com\\.petros\\.ireview\\.[^\"]+)\"(.*?)</action>",
                     java.util.regex.Pattern.DOTALL).matcher(manifest());
        while (action.find()) {
            var key = java.util.regex.Pattern
                .compile("keymap=\"([^\"]+)\"\\s+first-keystroke=\"([^\"]+)\"").matcher(action.group(2));
            while (key.find()) {
                out.add(new String[]{key.group(1), key.group(2), action.group(1)});
            }
        }
        return out;
    }

    @Test
    void noTwoOfThisPluginsActionsShareAKeystroke() throws Exception {
        // A duplicate is not a build error and not a runtime error: the IDE
        // silently picks one action and the other key does nothing, which
        // reads as "the plugin is broken" rather than as the typo it is.
        var owner = new java.util.HashMap<String, String>();
        for (String[] s : declaredShortcuts()) {
            String slot = s[0] + " | " + s[1];
            String previous = owner.put(slot, s[2]);
            assertNull(previous,
                "keystroke " + s[1] + " in keymap " + s[0] + " is claimed by both "
                    + previous + " and " + s[2]);
        }
    }

    @Test
    void everyActionThisPluginRegistersIsReachableFromAMacKeymap() throws Exception {
        // The panel advertises these keys; an action registered without one
        // would render as "unassigned" forever and never be pressable.
        var bound = new java.util.HashSet<String>();
        for (String[] s : declaredShortcuts()) {
            if (s[0].startsWith("Mac OS X")) bound.add(s[2]);
        }
        var registered = new java.util.ArrayList<String>();
        var m = java.util.regex.Pattern
            .compile("<action id=\"(com\\.petros\\.ireview\\.[^\"]+)\"").matcher(manifest());
        while (m.find()) registered.add(m.group(1));

        assertFalse(registered.isEmpty(), "expected this plugin to register actions");
        for (String id : registered) {
            assertTrue(bound.contains(id), id + " has no Mac keymap shortcut");
        }
    }

    @Test
    void noActionDeclaresADefaultKeymapShortcut() throws Exception {
        // A $default declaration is inherited by the macOS keymaps WITH a
        // control->meta conversion, so "control alt D" arrives as a second
        // binding, meta+alt+D, alongside the Mac one. The action then has two
        // shortcuts, the panel prints whichever sorts first, and the key the
        // user was told about is not the key the panel shows.
        for (String[] s : declaredShortcuts()) {
            assertNotEquals("$default", s[0],
                s[2] + " declares a $default shortcut (" + s[1] + "); on macOS that is inherited "
                    + "as a second, control->meta converted binding beside the Mac one");
        }
    }
}
