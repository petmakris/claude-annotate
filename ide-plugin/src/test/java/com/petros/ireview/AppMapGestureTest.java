package com.petros.ireview;

import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.*;

/** Tap or hold of Cmd+Shift+M, and the plugin.xml binding. */
class AppMapGestureTest {

    private static final long MS = 1_000_000L;

    @Test
    void aReleaseWithinTheTapTimeKeepsTheMapOpen() {
        var g = new AppMapActions.Gesture(0, true);
        assertFalse(g.sticky());
        assertFalse(g.released(299 * MS));
        assertTrue(g.sticky());
        assertFalse(g.released(2_000 * MS), "later releases never close a map that stays");
    }

    @Test
    void aReleaseAfterAHoldClosesTheMap() {
        var g = new AppMapActions.Gesture(0, true);
        assertTrue(g.released(301 * MS));
        assertFalse(g.sticky());
    }

    @Test
    void aMapShownWithoutAKeyStaysUntilClosed() {
        var g = new AppMapActions.Gesture(0, false);
        assertTrue(g.sticky());
        assertFalse(g.released(5_000 * MS));
    }

    @Test
    void theActionIsBoundToCmdShiftMOnBothMacKeymapsAndPromoted() throws Exception {
        String xml = Files.readString(Path.of("src/main/resources/META-INF/plugin.xml"));
        int at = xml.indexOf("id=\"" + AppMapActions.SHOW_ID + "\"");
        assertTrue(at > 0);
        String action = xml.substring(at, xml.indexOf("</action>", at));
        assertTrue(action.contains("keymap=\"Mac OS X 10.5+\" first-keystroke=\"meta shift M\""));
        assertTrue(action.contains("keymap=\"Mac OS X\"       first-keystroke=\"meta shift M\""));
        assertTrue(xml.contains("<actionPromoter implementation=\"com.petros.ireview.AppMapPromoter\"/>"));
    }

    @Test
    void repoRelativePathsUseForwardSlashesAndRefuseOutsiders() {
        assertEquals("svc/A.java", AppMapActions.repoRelative(Path.of("/w/shop"), "/w/shop/svc/A.java"));
        assertNull(AppMapActions.repoRelative(Path.of("/w/shop"), "/w/other/A.java"));
    }
}
