package com.petros.ireview;

import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Picking the ref that "Diff vs Base Branch" compares against, with no picker
 * popup. Pure: the service supplies what git said, this decides which ref wins.
 *
 * Vocabulary: "override" is the ref typed into Settings; "symbolic ref" is what
 * `git symbolic-ref refs/remotes/origin/HEAD` printed (empty when origin/HEAD
 * is not set, which is common on clones made with --single-branch); "known
 * refs" are the branches that actually exist in this repository.
 */
class BaseBranchResolverTest {

    private static final List<String> TYPICAL =
        List.of("origin/main", "origin/feature/x", "main", "feature/x");

    @Test
    void theSettingsOverrideBeatsEverything() {
        Optional<String> ref = BaseBranchResolver.resolve(
            "origin/develop", "refs/remotes/origin/main", TYPICAL);
        assertEquals(Optional.of("origin/develop"), ref);
    }

    @Test
    void anOverrideIsAcceptedEvenWhenTheRefIsNotKnownLocally() {
        // A ref can be valid and absent from our listing (a tag, a remote we
        // have not fetched). Reporting "unknown ref" is git's job, not ours.
        assertEquals(Optional.of("origin/nightly"),
            BaseBranchResolver.resolve("origin/nightly", "", List.of()));
    }

    @Test
    void aBlankOverrideIsIgnored() {
        assertEquals(Optional.of("origin/main"),
            BaseBranchResolver.resolve("   ", "", TYPICAL));
        assertEquals(Optional.of("origin/main"),
            BaseBranchResolver.resolve(null, "", TYPICAL));
    }

    @Test
    void anOverrideIsTrimmedBeforeUse() {
        assertEquals(Optional.of("origin/develop"),
            BaseBranchResolver.resolve("  origin/develop \n", "", TYPICAL));
    }

    @Test
    void originHeadWinsWhenNoOverrideIsSet() {
        assertEquals(Optional.of("origin/develop"),
            BaseBranchResolver.resolve("", "refs/remotes/origin/develop",
                List.of("origin/develop", "origin/main")),
            "the repository's own default branch beats our guesses");
    }

    @Test
    void aStaleOriginHeadIsSkipped() {
        // origin/HEAD can point at a branch that has since been deleted.
        // Falling through to the guesses beats diffing against nothing.
        assertEquals(Optional.of("origin/main"),
            BaseBranchResolver.resolve("", "refs/remotes/origin/gone", TYPICAL));
    }

    @Test
    void fallsToOriginMainThenOriginMasterThenLocal() {
        assertEquals(Optional.of("origin/main"),
            BaseBranchResolver.resolve("", "", List.of("origin/main", "origin/master", "main")));
        assertEquals(Optional.of("origin/master"),
            BaseBranchResolver.resolve("", "", List.of("origin/master", "main", "master")));
        assertEquals(Optional.of("main"),
            BaseBranchResolver.resolve("", "", List.of("main", "master")));
        assertEquals(Optional.of("master"),
            BaseBranchResolver.resolve("", "", List.of("master", "feature/x")));
    }

    @Test
    void resolvesToNothingWhenTheRepositoryHasNoRecognisableBaseBranch() {
        assertEquals(Optional.empty(),
            BaseBranchResolver.resolve("", "", List.of("trunk", "feature/x")),
            "better to say which refs were tried than to diff against a guess");
    }

    // ---- ref-name normalisation ------------------------------------------

    @Test
    void remoteRefPathsAreShortenedToBranchNames() {
        assertEquals("origin/main", BaseBranchResolver.shortName("refs/remotes/origin/main"));
    }

    @Test
    void localRefPathsAreShortenedToBranchNames() {
        assertEquals("main", BaseBranchResolver.shortName("refs/heads/main"));
    }

    @Test
    void anAlreadyShortNameIsLeftAlone() {
        assertEquals("origin/main", BaseBranchResolver.shortName("origin/main"));
    }

    @Test
    void surroundingWhitespaceFromGitOutputIsStripped() {
        assertEquals("origin/main", BaseBranchResolver.shortName("refs/remotes/origin/main\n"));
    }

    @Test
    void theRefsTriedAreReportableSoAFailureCanExplainItself() {
        assertEquals(List.of("origin/main", "origin/master", "main", "master"),
            BaseBranchResolver.candidates());
    }
}
