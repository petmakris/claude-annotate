package com.petros.ireview;

import org.junit.jupiter.api.Test;

import java.util.List;

import static com.petros.ireview.AppMapLights.Kind.*;
import static org.junit.jupiter.api.Assertions.*;

class AppMapLightsTest {

    private static AppMapFile.Place at(String part) { return new AppMapFile.Place(part, null, false); }
    private static AppMapFile.Place at(String part, String sub) { return new AppMapFile.Place(part, sub, true); }

    @Test
    void aBranchLightsEveryPartItChangesOnceAndSkipsFilesOnNoPart() {
        var m = AppMapLights.changed(List.of(at("svc"), at("web"), at("svc"), at(null)), null);
        assertEquals(List.of("svc", "web"), List.copyOf(m.keySet()));
        assertTrue(m.values().stream().allMatch(x -> x.kind() == CHANGED && x.number() == null));
    }

    @Test
    void onADetailMapOnlyTheSubPartsOfThatDetailLight() {
        var m = AppMapLights.changed(List.of(at("svc", "svc-api"), at("svc", null), at("web")), "svc");
        assertEquals(List.of("svc-api"), List.copyOf(m.keySet()));
    }

    @Test
    void morTabsInAPartMakeItHotterAndTheBusiestIsFull() {
        var m = AppMapLights.tabs(List.of(at("svc"), at("svc"), at("svc"), at("web"), at("orders"), at("orders")), null);
        assertEquals(1.0, m.get("svc").heat(), 1e-9);
        assertEquals(0.25, m.get("web").heat(), 1e-9);
        assertEquals(0.625, m.get("orders").heat(), 1e-9);
        assertEquals(HEAT, m.get("web").kind());
    }

    @Test
    void oneTabEverywhereIsFullHeat() {
        assertEquals(1.0, AppMapLights.tabs(List.of(at("svc")), null).get("svc").heat(), 1e-9);
    }

    @Test
    void usersLightAmberButTheOpenFilesOwnPartStaysHere() {
        var m = AppMapLights.users(at("svc"), List.of(at("svc"), at("web"), at("orders")), null);
        assertEquals(HERE, m.get("svc").kind());
        assertEquals(USER, m.get("web").kind());
        assertEquals(USER, m.get("orders").kind());
        assertEquals(3, m.size());
    }

    @Test
    void stepsCarryTheNumberOfTheirFirstStepAndTheCurrentOneIsHere() {
        var steps = List.of(at("web"), at("svc"), at("web"), at("orders"));
        var m = AppMapLights.steps(steps, 2, null);
        assertEquals(new AppMapLights.Mark(HERE, 1, "3"), m.get("web"));
        assertEquals(new AppMapLights.Mark(STEP, 1, "2"), m.get("svc"));
        assertEquals(new AppMapLights.Mark(STEP, 1, "4"), m.get("orders"));
        assertEquals(List.of("web", "svc", "orders"), AppMapLights.trail(steps, null));
    }
}
