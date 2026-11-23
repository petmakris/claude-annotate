package com.petros.ireview;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;

class AppMapStoreTest {

    private static void putMap(Path home, String name) throws Exception {
        Path dir = Files.createDirectories(home.resolve(name));
        Files.copy(AppMapFileTest.SAMPLE, dir.resolve("map.json"),
            java.nio.file.StandardCopyOption.REPLACE_EXISTING);
    }

    private static Path repo(Path root, String name, String remoteUrl) throws Exception {
        Path repo = Files.createDirectories(root.resolve(name));
        Path git = Files.createDirectories(repo.resolve(".git"));
        String cfg = "[core]\n\tbare = false\n";
        if (remoteUrl != null) cfg += "[remote \"origin\"]\n\turl = " + remoteUrl + "\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n";
        Files.writeString(git.resolve("config"), cfg);
        return repo;
    }

    @Test
    void remotesAreNormalisedToHostAndPath() {
        assertEquals("github.com/acme/shop", AppMapStore.normaliseRemote("git@github.com:Acme/Shop.git"));
        assertEquals("github.com/acme/shop", AppMapStore.normaliseRemote("https://user@github.com/acme/shop.git"));
        assertEquals("github.com/acme/shop", AppMapStore.normaliseRemote("ssh://git@github.com/acme/shop"));
        assertEquals("github.com/acme/shop", AppMapStore.normaliseRemote("https://github.com/acme/shop/"));
    }

    @Test
    void aRepoIsFoundByItsRemoteFromAFolderInsideIt(@TempDir Path tmp) throws Exception {
        Path home = tmp.resolve("home");
        putMap(home, "shop");
        Path repo = repo(tmp, "checkout", "git@github.com:Acme/Shop.git");
        Path inside = Files.createDirectories(repo.resolve("svc"));
        Optional<AppMapStore.Found> found = new AppMapStore(home).find(inside);
        assertTrue(found.isPresent());
        assertEquals(repo.toRealPath(), found.get().repoRoot().toRealPath());
        assertEquals("shop", found.get().map().name());
    }

    @Test
    void aWorktreeWhoseGitIsAFileStillFindsTheRemote(@TempDir Path tmp) throws Exception {
        Path home = tmp.resolve("home");
        putMap(home, "shop");
        Path main = repo(tmp, "main", "https://github.com/acme/shop.git");
        Path wtGit = Files.createDirectories(main.resolve(".git/worktrees/w"));
        Files.writeString(wtGit.resolve("commondir"), "../..\n");
        Path wt = Files.createDirectories(tmp.resolve("w"));
        Files.writeString(wt.resolve(".git"), "gitdir: " + wtGit + "\n");
        Optional<AppMapStore.Found> found = new AppMapStore(home).find(wt);
        assertTrue(found.isPresent());
        assertEquals(wt.toRealPath(), found.get().repoRoot().toRealPath());
    }

    @Test
    void noRemoteAndNoFolderMatchFindsNothing(@TempDir Path tmp) throws Exception {
        Path home = tmp.resolve("home");
        putMap(home, "shop");
        Path repo = repo(tmp, "bare", null);
        assertTrue(new AppMapStore(home).find(repo).isEmpty());
        Path other = repo(tmp, "other", "git@github.com:acme/other.git");
        assertTrue(new AppMapStore(home).find(other).isEmpty());
        assertTrue(new AppMapStore(tmp.resolve("no-such-home")).find(other).isEmpty());
    }

    @Test
    void twoMatchingMapsGiveTheNewerOne(@TempDir Path tmp) throws Exception {
        Path home = tmp.resolve("home");
        putMap(home, "old");
        putMap(home, "new");
        Files.setLastModifiedTime(home.resolve("old/map.json"), FileTime.fromMillis(1_000_000_000_000L));
        Files.setLastModifiedTime(home.resolve("new/map.json"), FileTime.fromMillis(1_700_000_000_000L));
        Path repo = repo(tmp, "c", "git@github.com:acme/shop.git");
        // Both files are copies of the sample, so tell them apart by the name inside.
        Files.writeString(home.resolve("new/map.json"),
            Files.readString(AppMapFileTest.SAMPLE).replace("\"name\": \"shop\"", "\"name\": \"newer\""));
        Files.setLastModifiedTime(home.resolve("new/map.json"), FileTime.fromMillis(1_700_000_000_000L));
        assertEquals("newer", new AppMapStore(home).find(repo).orElseThrow().map().name());
    }

    @Test
    void aMapMatchedByFolderIsFoundWithoutAGitRepo(@TempDir Path tmp) throws Exception {
        Path home = tmp.resolve("home");
        Path folder = Files.createDirectories(tmp.resolve("plain"));
        Files.createDirectories(home.resolve("shop"));
        Files.writeString(home.resolve("shop/map.json"), Files.readString(AppMapFileTest.SAMPLE)
            .replace("/work/shop", folder.toString().replace("\\", "\\\\")));
        var found = new AppMapStore(home).find(folder);
        assertTrue(found.isPresent());
        assertEquals(folder, found.get().repoRoot());
    }

    @Test
    void aMatchedMapThatCannotBeReadIsReportedNotHidden(@TempDir Path tmp) throws Exception {
        Path home = tmp.resolve("home");
        Files.createDirectories(home.resolve("shop"));
        Files.writeString(home.resolve("shop/map.json"),
            Files.readString(AppMapFileTest.SAMPLE).replace("\"version\": 1", "\"version\": 9"));
        Path repo = repo(tmp, "c", "git@github.com:acme/shop.git");
        assertThrows(AppMapFile.Unreadable.class, () -> new AppMapStore(home).find(repo));
    }

    @Test
    void aRebuiltMapIsPickedUpWithoutARestart(@TempDir Path tmp) throws Exception {
        Path home = tmp.resolve("home");
        putMap(home, "shop");
        Path repo = repo(tmp, "c", "git@github.com:acme/shop.git");
        AppMapStore store = new AppMapStore(home);
        assertEquals("shop", store.find(repo).orElseThrow().map().name());
        Path f = home.resolve("shop/map.json");
        Files.writeString(f, Files.readString(f).replace("\"name\": \"shop\"", "\"name\": \"again\""));
        Files.setLastModifiedTime(f, FileTime.fromMillis(Files.getLastModifiedTime(f).toMillis() + 5000));
        assertEquals("again", store.find(repo).orElseThrow().map().name());
    }
}
