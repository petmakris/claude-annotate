package com.petros.ireview;

import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Structural guards on "Annotate with Git Blame" inside the Smart Diff viewer.
 *
 * The whole feature is one tag on each side's content. {@code
 * AnnotateDiffViewerAction} reads exactly one thing — {@code
 * DiffVcsDataKeys.REVISION_INFO} — and offers the gutter blame when it finds it.
 * Lose the tag and nothing fails: the action simply stops appearing in the
 * context menu, with no error anywhere, which is how it was absent in the first
 * place. That is worth a test even though the tag itself needs a running IDE.
 */
class DiffAnnotationTest {

    private static String service() throws Exception {
        return Files.readString(Path.of("src/main/java/com/petros/ireview/SmartDiffService.java"));
    }

    @Test
    void contentIsTaggedWithTheRevisionItCameFrom() throws Exception {
        String s = service();
        assertTrue(s.contains("DiffVcsDataKeys.REVISION_INFO"),
            "without this key the diff's Annotate action never appears, and nothing reports why");
        assertTrue(s.contains("putUserData(DiffVcsDataKeys.REVISION_INFO"),
            "the key belongs on the DiffContent, which is where the action looks for it");
    }

    @Test
    void theTagCarriesBothAFilePathAndARevisionNumber() throws Exception {
        // The key's type is Pair<FilePath, VcsRevisionNumber>. Blame needs both:
        // the path says what to blame, the revision says as of when.
        String s = service();
        assertTrue(s.contains("Pair.create(path, new GitRevisionNumber("),
            "REVISION_INFO is a Pair of the file path and the revision to blame against");
    }

    @Test
    void everySideThatCameFromACommitCarriesThatCommit() throws Exception {
        // Three keys build a left side from bytes — the walk, the base branch and
        // HEAD — and each has to pass its revision or that one diff loses blame
        // while the other two keep it, which reads as the feature being flaky.
        String s = service();
        assertTrue(s.contains("shortRef(step.left()), step.left())"),
            "the walk's left side must pass its commit");
        assertTrue(s.contains("\"HEAD\", revisions.get(0))"),
            "Compare with HEAD must pass the commit it resolved HEAD to");
        assertTrue(s.contains("resolve(repo, base.get())"),
            "the base branch must be resolved to a commit before it is used for blame");
    }

    @Test
    void aBranchNameIsResolvedToACommitBeforeItIsBlamed() throws Exception {
        // A ref that moves cannot identify the lines it moved past: blaming
        // against "pr-base" would mean something different after the next push.
        String s = service();
        assertTrue(s.contains("GitCommand.REV_PARSE") && s.contains("^{commit}"),
            "resolve() should ask git for the commit a ref names");
        assertTrue(s.contains("private @Nullable String resolve("),
            "resolution has to be allowed to fail — an unfetched ref is not an error worth interrupting for");
    }

    @Test
    void theWorkingCopySideIsNotTagged() throws Exception {
        // It is the real file on disk. The IDE annotates that on its own, and a
        // revision tag would claim it is a commit, which it is not.
        String s = service();
        assertTrue(s.contains("new Side(null, \"Working copy\", null)"),
            "the working copy has no bytes and no revision");
        assertTrue(s.contains("if (side.bytes() == null)"),
            "content() must hand the live file through untagged");
    }
}
