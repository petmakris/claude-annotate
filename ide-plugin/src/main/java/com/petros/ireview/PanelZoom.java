package com.petros.ireview;

import com.intellij.ide.util.PropertiesComponent;

import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Persisted zoom level for the review panel's rendered content — a pixel
 * delta applied on top of the theme's computed prose/mono font sizes in
 * {@link SynthesisBrowser} and the {@link ThreadConversationView} fallback
 * renderer. Stored once per IDE (not per project) via
 * {@link PropertiesComponent}, mirroring how the Terminal tool window
 * persists its own font size independently of the editor.
 */
final class PanelZoom {

    private static final String KEY = "ireview.zoom.delta";
    private static final int MIN = -6;
    private static final int MAX = 16;
    private static final int STEP = 2;

    private static final CopyOnWriteArrayList<Runnable> listeners = new CopyOnWriteArrayList<>();

    private PanelZoom() {}

    static int delta() {
        return PropertiesComponent.getInstance().getInt(KEY, 0);
    }

    static void increase() {
        setDelta(clamp(delta() + STEP));
    }

    static void decrease() {
        setDelta(clamp(delta() - STEP));
    }

    static void reset() {
        setDelta(0);
    }

    static boolean canIncrease() {
        return delta() < MAX;
    }

    static boolean canDecrease() {
        return delta() > MIN;
    }

    private static void setDelta(int value) {
        if (value == delta()) return;
        PropertiesComponent.getInstance().setValue(KEY, value, 0);
        for (Runnable l : listeners) l.run();
    }

    private static int clamp(int v) {
        return Math.max(MIN, Math.min(MAX, v));
    }

    /** Called whenever the zoom level changes, so every open thread view can
     *  re-render at the new size immediately. */
    static void addListener(Runnable r) {
        listeners.add(r);
    }

    static void removeListener(Runnable r) {
        listeners.remove(r);
    }
}
