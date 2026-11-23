package com.petros.ireview;

import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Structural guards on where a Smart Diff result is shown.
 *
 * {@link DiffSurface} cannot be exercised without a running IDE — it needs a
 * Project, a FileEditorManager and the platform's diff machinery. What can be
 * checked without one is that the code still routes the way the fix requires,
 * which is the part a later edit would undo by accident.
 */
class DiffSurfaceTest {

    private static String source(String simpleName) throws Exception {
        return Files.readString(Path.of("src/main/java/com/petros/ireview/" + simpleName + ".java"));
    }

    @Test
    void theServiceNeverShowsADiffThroughDiffManagerDirectly() throws Exception {
        // DiffManager.showDiff builds a fresh ChainDiffVirtualFile or a fresh
        // DiffWindow on every call, so nothing it opens can ever be reused. Nine
        // presses of the key produced nine windows. Going through DiffSurface is
        // the only reason that stopped.
        String service = source("SmartDiffService");
        assertFalse(service.contains("DiffManager.getInstance()"),
            "SmartDiffService must show diffs through DiffSurface, which can replace the previous one");
        assertTrue(service.contains("surface.replaceWith("),
            "SmartDiffService should hand its request to the owned surface");
    }

    @Test
    void everyDiffTheServiceShowsGoesThroughTheOneSurface() throws Exception {
        // Three keys produce a diff — Smart Diff, base branch, HEAD — and all
        // three reach the screen through the same private show(...) helper. If a
        // fourth ever bypasses it, that key alone starts stacking again.
        String service = source("SmartDiffService");
        assertEquals(1, countOf(service, "surface.replaceWith("),
            "more than one call site means the surface is no longer the single way out");
    }

    @Test
    void theSurfaceClosesThePreviousDiffBeforeOpeningTheNext() throws Exception {
        String surface = source("DiffSurface");
        int close = surface.indexOf("closePrevious();");
        int open = surface.indexOf("prefersTab()");
        assertTrue(close >= 0, "DiffSurface must close what the last press opened");
        assertTrue(close < open, "the previous diff has to be closed before the next one is opened");
    }

    @Test
    void theSurfaceRespectsTheUsersWindowOrTabPreference() throws Exception {
        // Forcing one or the other would override a setting the person chose in
        // Settings -> Advanced Settings -> Version Control.
        String surface = source("DiffSurface");
        assertTrue(surface.contains("show.diff.as.editor.tab"),
            "the tab-or-window decision must read IntelliJ's own setting");
        assertTrue(surface.contains("show.diff.as.frame"),
            "the registry override has to be honoured too, or a frame user silently gets tabs");
        assertTrue(surface.contains("ChainDiffVirtualFile") && surface.contains("showDiffBuiltin"),
            "both routes must exist; one branch alone means one preference is ignored");
    }

    private static int countOf(String haystack, String needle) {
        int n = 0;
        for (int i = haystack.indexOf(needle); i >= 0; i = haystack.indexOf(needle, i + needle.length())) n++;
        return n;
    }
}
