package com.petros.ireview;

import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class PrDiffRequestTest {

    private static PrDiffRequest.Parsed parse(String target, String... kv) {
        Map<String, String> params = new HashMap<>();
        for (int i = 0; i < kv.length; i += 2) params.put(kv[i], kv[i + 1]);
        return PrDiffRequest.parse(target, params);
    }

    @Test
    void aFullLinkKeepsEveryParameter() {
        PrDiffRequest.Parsed p = parse("pr-diff", "number", "6433", "repo", "acme/shop",
            "branch", "TICKET-291-x", "path", "/abs/checkout", "id", "PR_kw1");
        assertNull(p.error());
        assertEquals(new PrDiffRequest(6433, "/abs/checkout", "TICKET-291-x", "acme/shop", "PR_kw1"), p.request());
    }

    @Test
    void onlyTheNumberIsRequired() {
        PrDiffRequest.Parsed p = parse("pr-diff", "number", "7");
        assertEquals(new PrDiffRequest(7, null, null, null, null), p.request());
    }

    @Test
    void aBlankPathOrBranchIsAbsent() {
        PrDiffRequest r = parse("pr-diff", "number", "7", "path", "  ", "branch", "", "repo", " ", "id", "").request();
        assertEquals(new PrDiffRequest(7, null, null, null, null), r);
    }

    @Test
    void aMissingNumberIsRefusedWithItsMessage() {
        PrDiffRequest.Parsed p = parse("pr-diff", "repo", "acme/shop");
        assertNull(p.request());
        assertEquals("ireview pr-diff: missing or bad number 'null'", p.error());
    }

    @Test
    void aNumberThatIsNotAPositiveIntegerIsRefused() {
        for (String bad : new String[] {"abc", "0", "-5", "", "12x", "1.5", "99999999999999999999"}) {
            PrDiffRequest.Parsed p = parse("pr-diff", "number", bad);
            assertNull(p.request(), bad);
            assertEquals("ireview pr-diff: missing or bad number '" + bad + "'", p.error());
        }
    }

    @Test
    void anUnknownOrMissingTargetIsRefused() {
        assertEquals("ireview: unknown command 'walkthrough'", parse("walkthrough", "number", "7").error());
        assertEquals("ireview: unknown command 'null'", parse(null, "number", "7").error());
    }
}
