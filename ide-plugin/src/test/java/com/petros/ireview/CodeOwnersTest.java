package com.petros.ireview;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class CodeOwnersTest {

    @Test
    void theLastMatchingRuleGivesTheOwnersAndSectionsAreSkipped(@TempDir Path repo) throws Exception {
        Files.createDirectories(repo.resolve(".github"));
        Files.writeString(repo.resolve(".github/CODEOWNERS"), """
            # who owns what

            /svc/ @acme/core
            [Section]
            /svc/src/**/java/com/acme/svc/orders/** @acme/orders @acme/lead  # trailing note
            """);
        CodeOwners o = CodeOwners.at(repo);
        assertEquals(List.of("@acme/orders", "@acme/lead"),
            o.owners("svc/src/main/java/com/acme/svc/orders/Order.java"));
        assertEquals(List.of("@acme/core"),
            o.owners("svc/src/main/java/com/acme/svc/billing/Bill.java"));
        assertEquals(List.of(), o.owners("lib/x"));
    }

    @Test
    void noFileMeansNoOwners(@TempDir Path repo) {
        assertEquals(List.of(), CodeOwners.at(repo).owners("a/b.java"));
    }

    @Test
    void theFirstFileFoundWinsAndAChangeIsPickedUp(@TempDir Path repo) throws Exception {
        Files.writeString(repo.resolve("CODEOWNERS"), "* @acme/root\n");
        Files.createDirectories(repo.resolve("docs"));
        Files.writeString(repo.resolve("docs/CODEOWNERS"), "* @acme/docs\n");
        assertEquals(List.of("@acme/root"), CodeOwners.at(repo).owners("a.txt"));
        Files.writeString(repo.resolve("CODEOWNERS"), "* @acme/changed\n");
        Files.setLastModifiedTime(repo.resolve("CODEOWNERS"), java.nio.file.attribute.FileTime.fromMillis(
            System.currentTimeMillis() + 10_000));
        assertEquals(List.of("@acme/changed"), CodeOwners.at(repo).owners("a.txt"));
    }
}
