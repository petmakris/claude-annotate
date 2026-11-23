package com.petros.ireview;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class AppMapFileTest {

    static final Path SAMPLE = Path.of("../skills/app_map/tests/sample_map.json");

    private static AppMapFile sample() throws Exception {
        return AppMapFile.read(SAMPLE);
    }

    @Test
    void aFileOnAPartWithNoDetailIsOnThatPartOnly() throws Exception {
        AppMapFile.Place p = sample().place("svc/src/main/java/com/acme/svc/orders/A.java");
        assertEquals("orders", p.part());
        assertNull(p.subPart());
        assertFalse(p.hasDetail());
    }

    @Test
    void aFileOnASubPartNamesBothLevels() throws Exception {
        AppMapFile.Place p = sample().place("svc/src/main/java/com/acme/svc/api/Api.java");
        assertEquals("svc", p.part());
        assertEquals("svc-api", p.subPart());
        assertTrue(p.hasDetail());
    }

    @Test
    void aFileOnATopPartButNoSubPartIsStillOnTheTopPart() throws Exception {
        AppMapFile.Place p = sample().place("svc/src/main/java/com/acme/svc/util/U.java");
        assertEquals("svc", p.part());
        assertNull(p.subPart());
        assertTrue(p.hasDetail());
    }

    @Test
    void aFileOnNoPartSaysSo() throws Exception {
        AppMapFile.Place p = sample().place("lib/x.java");
        assertNull(p.part());
        assertNull(p.subPart());
        assertFalse(p.hasDetail());
    }

    @Test
    void aPartShowsAPillForEachTeamWithAFifthOfItsFiles() throws Exception {
        var m = sample();
        // svc: core 120 of 128, the 8 uncovered files are under a fifth.
        assertEquals(List.of(new AppMapFile.Pill("CORE", "@acme/core")), m.pills("svc"));
        // web: no label in the map, so the name's last part in capitals; core's 2 of 32 is under a fifth.
        assertEquals(List.of(new AppMapFile.Pill("WEB", "@acme/web")), m.pills("web"));
        // svc-db: no team at all.
        assertEquals(List.of(new AppMapFile.Pill("No owner", null)), m.pills("svc-db"));
        assertTrue(m.pills("nope").isEmpty());
    }

    @Test
    void aFileBelongsToTheDeepestModuleFolderThatHoldsIt() throws Exception {
        var m = sample();
        assertEquals("svc", m.module("svc/src/main/java/A.java"));
        assertEquals("svc-api", m.module("svc/api/src/main/java/B.java"));
        assertEquals("web", m.module("web/x.ts"));
        assertNull(m.module("webby/x.ts"));
        assertNull(m.module("README.md"));
    }

    @Test
    void aFileIsMatchedOnlyAgainstThePartsOfItsOwnRepo() throws Exception {
        var m = sample();
        assertEquals("contract", m.repoNameFor("git@github.com:Acme/Contract.git"));
        assertNull(m.repoNameFor("git@github.com:acme/shop.git"));
        // Both repos have a svc folder: the main repo's file is on svc, the contract's on shared.
        assertEquals("svc", m.place("svc/Thing.java", null).part());
        assertEquals("shared", m.place("svc/Thing.java", "contract").part());
        assertNull(m.place("web/x.ts", "contract").part());
        assertEquals("contract-svc", m.module("svc/Thing.java", "contract"));
        assertEquals("svc", m.module("svc/Thing.java", null));
    }

    @Test
    void ownersListTheBiggestTeamFirst() throws Exception {
        var owners = sample().owners("svc");
        assertEquals("@acme/core", owners.get(0).team());
        assertEquals(120, owners.get(0).files());
        assertNull(owners.get(1).team());
        assertTrue(sample().owners("nope").isEmpty());
    }

    @Test
    void drawingsAndDetailIdsAreRead() throws Exception {
        AppMapFile f = sample();
        assertEquals(600, f.drawing("top").width);
        assertEquals(400, f.drawing("svc").width);
        assertNull(f.drawing("orders"));
        assertEquals(java.util.Set.of("svc"), f.detailIds());
        assertEquals("2026-11-23T10:00:00Z", f.builtAt());
    }

    @Test
    void rejectsUnknownVersion(@TempDir Path tmp) throws Exception {
        Path p = tmp.resolve("map.json");
        Files.writeString(p, Files.readString(SAMPLE).replace("\"version\": 1", "\"version\": 2"));
        AppMapFile.Unreadable e = assertThrows(AppMapFile.Unreadable.class, () -> AppMapFile.read(p));
        assertTrue(e.getMessage().contains("2"), e.getMessage());
    }

    @Test
    void rejectsBrokenJson(@TempDir Path tmp) throws Exception {
        Path p = tmp.resolve("map.json");
        Files.writeString(p, "{\"version\": 1, \"parts\": [");
        assertThrows(AppMapFile.Unreadable.class, () -> AppMapFile.read(p));
        assertThrows(AppMapFile.Unreadable.class, () -> AppMapFile.read(tmp.resolve("missing.json")));
    }

    @Test
    void theEditorPillLabelsTheFilesTeamsAsTheMapDoesAndSaysNoOwnerWhenThereIsNone() throws Exception {
        var m = sample();
        var tags = AppMapEditorPill.teams(m, java.util.List.of("@acme/orders", "@acme/core"));
        assertEquals(java.util.List.of("ORD", "CORE"), tags.stream().map(AppMapCanvas.Tag::text).toList());
        assertEquals(AppMapCanvas.teamColours(m).get("@acme/orders"), tags.get(0).color());
        assertEquals(java.util.List.of("No owner"),
            AppMapEditorPill.teams(m, java.util.List.of()).stream().map(AppMapCanvas.Tag::text).toList());
    }
}
