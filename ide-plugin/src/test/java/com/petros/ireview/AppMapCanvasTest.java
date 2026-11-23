package com.petros.ireview;

import org.junit.jupiter.api.Test;

import java.awt.*;
import java.awt.image.BufferedImage;

import static org.junit.jupiter.api.Assertions.*;

class AppMapCanvasTest {

    private static final Rectangle AREA = new Rectangle(0, 0, 1200, 600);

    private static BufferedImage paint(String lit) throws Exception {
        AppMapFile.Drawing d = AppMapFile.read(AppMapFileTest.SAMPLE).drawing("top");
        BufferedImage img = new BufferedImage(1200, 600, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = img.createGraphics();
        g.setColor(AppMapCanvas.Palette.light().background());
        g.fillRect(0, 0, 1200, 600);
        AppMapCanvas.paint(g, d, AREA, 2.0, lit, AppMapCanvas.Palette.light());
        g.dispose();
        return img;
    }

    // The sample is 600x300 painted at 2x into 1200x600. A pixel inside a box but
    // to the right of its words, at (x + w - 10, y + h / 2), is flat fill.
    private static final int ORDERS_X = (40 + 180 - 10) * 2, ORDERS_Y = (196 + 30) * 2;
    private static final int WEB_X = (380 + 180 - 10) * 2, WEB_Y = (120 + 30) * 2;

    @Test
    void theLitBoxIsFilledWithTheAccentAndAnUnlitOneIsNot() throws Exception {
        BufferedImage img = paint("orders");
        var p = AppMapCanvas.Palette.light();
        assertEquals(p.accentFill().getRGB(), img.getRGB(ORDERS_X, ORDERS_Y));
        assertNotEquals(p.accentFill().getRGB(), img.getRGB(WEB_X, WEB_Y));
    }

    @Test
    void withNothingLitNoBoxHasTheAccentFill() throws Exception {
        BufferedImage img = paint(null);
        var p = AppMapCanvas.Palette.light();
        assertNotEquals(p.accentFill().getRGB(), img.getRGB(ORDERS_X, ORDERS_Y));
        assertNotEquals(p.accentFill().getRGB(), img.getRGB(WEB_X, WEB_Y));
    }

    @Test
    void anArrowOfTheLitPartIsDrawnInTheAccent() throws Exception {
        // edge:orders->svc#0 is a vertical dashed arrow at x=130 from y=196 to 180.
        BufferedImage lit = paint("orders");
        BufferedImage plain = paint(null);
        int accent = AppMapCanvas.Palette.light().accent().getRGB();
        boolean found = false;
        for (int y = 360; y < 395 && !found; y++)
            for (int x = 256; x < 264 && !found; x++)
                found = lit.getRGB(x, y) == accent;
        assertTrue(found, "no accent pixel on the lit part's arrow");
        for (int y = 360; y < 395; y++)
            for (int x = 256; x < 264; x++)
                assertNotEquals(accent, plain.getRGB(x, y));
    }

    @Test
    void keyAtFindsTheBoxUnderThePointAndNothingInTheCorner() throws Exception {
        AppMapFile.Drawing d = AppMapFile.read(AppMapFileTest.SAMPLE).drawing("top");
        assertEquals("box:web", AppMapCanvas.keyAt(d, AREA, 2.0, new Point(470 * 2, 150 * 2)));
        assertEquals("box:orders", AppMapCanvas.keyAt(d, AREA, 2.0, new Point(130 * 2, 226 * 2)));
        assertNull(AppMapCanvas.keyAt(d, AREA, 2.0, new Point(1190, 590)));
    }

    @Test
    void theDrawingIsCentredAndNeverScaledPastTheMaximum() throws Exception {
        AppMapFile.Drawing d = AppMapFile.read(AppMapFileTest.SAMPLE).drawing("top");
        var t = AppMapCanvas.layout(d, AREA, 1.0);
        assertEquals(1.0, t.scale(), 1e-9);
        assertEquals(300.0, t.x(), 1e-9);
        assertEquals(150.0, t.y(), 1e-9);
        assertEquals(1.0, AppMapCanvas.layout(d, new Rectangle(0, 0, 300, 600), 1.0).scale() * 2, 1e-9);
    }

    @Test
    void aBoxsToneIsIgnoredSoOnlyTheLitPartHasColour() throws Exception {
        AppMapFile.Drawing d = AppMapFile.read(AppMapFileTest.SAMPLE).drawing("top");
        BufferedImage img = new BufferedImage(1200, 600, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = img.createGraphics();
        var p = AppMapCanvas.Palette.light();
        g.setColor(p.background());
        g.fillRect(0, 0, 1200, 600);
        AppMapCanvas.paint(g, d, AREA, 2.0, null, p);
        g.dispose();
        // box:orders is blue in the sample; inside its right edge (x 40+180, y 196..256) the fill is the plain box fill.
        assertEquals(p.boxFill().getRGB(), img.getRGB((220 - 4) * 2, 250 * 2));
    }

    @Test
    void anArrowIntoTheBoxHoldingTheLitSliceIsLitToo() throws Exception {
        AppMapFile.Drawing d = AppMapFile.read(AppMapFileTest.SAMPLE).drawing("top");
        // A frame box around box:orders (40..220 x 196..256), and an arrow from box:web into the frame.
        AppMapFile.Shape frame = new AppMapFile.Shape();
        frame.kind = "rect"; frame.role = "box"; frame.key = "box:frame"; frame.x = 30; frame.y = 190; frame.w = 200; frame.h = 74; frame.r = 8;
        AppMapFile.Shape arrow = new AppMapFile.Shape();
        arrow.kind = "path"; arrow.role = "arrow"; arrow.key = "edge:web->frame#0"; arrow.arrow = true;
        arrow.points = new double[][]{{470, 180}, {470, 230}, {234, 230}};
        d.shapes = new java.util.ArrayList<>(d.shapes);
        d.shapes.add(0, frame);
        d.shapes.add(arrow);
        BufferedImage img = new BufferedImage(1200, 600, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = img.createGraphics();
        var p = AppMapCanvas.Palette.light();
        g.setColor(p.background());
        g.fillRect(0, 0, 1200, 600);
        AppMapCanvas.paint(g, d, AREA, 2.0, "orders", p);
        g.dispose();
        // On the arrow's horizontal run (y 230, x 300..440) the colour is the accent.
        assertEquals(p.accent().getRGB(), img.getRGB(360 * 2, 230 * 2));
        assertEquals(java.util.List.of("frame"), AppMapCanvas.holdersOutermostFirst(d, "orders"));
        assertTrue(AppMapCanvas.holdersOutermostFirst(d, "web").isEmpty());
    }

    @Test
    void onABlankLastLineThePillsStartAtTheTextsLeftEdge() throws Exception {
        AppMapFile.Drawing d = AppMapFile.read(AppMapFileTest.SAMPLE).drawing("top");
        AppMapFile.Shape row = new AppMapFile.Shape();
        row.kind = "text"; row.role = "line"; row.key = "box:web"; row.x = 398; row.y = 172; row.size = 13; row.weight = 400;
        AppMapFile.Run blank = new AppMapFile.Run();
        blank.text = "\u00a0";
        row.runs = java.util.List.of(blank);
        d.shapes = new java.util.ArrayList<>(d.shapes);
        d.shapes.add(row);
        BufferedImage img = new BufferedImage(1200, 600, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = img.createGraphics();
        var p = AppMapCanvas.Palette.light();
        g.setColor(p.background());
        g.fillRect(0, 0, 1200, 600);
        Color team = new Color(200, 30, 140);
        AppMapCanvas.paint(g, d, AREA, 2.0, null, p,
            java.util.Map.of("box:web", java.util.List.of(new AppMapCanvas.Tag("WEB", team))));
        g.dispose();
        // The pill starts at the line's x (398) and is centred 4.5 px above its baseline (172).
        Color fill = AppMapCanvas.mix(team, Color.WHITE, 0.82);
        assertEquals(fill.getRGB(), img.getRGB((398 + 3) * 2, (172 - 4) * 2));
        // The right end of the name line above stays clear of it.
        assertNotEquals(fill.getRGB(), img.getRGB((560 - 15) * 2, (150 - 4) * 2));
    }

    @Test
    void aTeamPillSitsInsideTheBoxAtTheRightEnd() throws Exception {
        AppMapFile.Drawing d = AppMapFile.read(AppMapFileTest.SAMPLE).drawing("top");
        BufferedImage img = new BufferedImage(1200, 600, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = img.createGraphics();
        var p = AppMapCanvas.Palette.light();
        g.setColor(p.background());
        g.fillRect(0, 0, 1200, 600);
        Color team = new Color(200, 30, 140);
        AppMapCanvas.paint(g, d, AREA, 2.0, null, p,
            java.util.Map.of("box:web", java.util.List.of(new AppMapCanvas.Tag("WEB", team))));
        g.dispose();
        // box:web is x 380..560, y 120..180; its only text line has its baseline at y 150. The pill ends 12 px
        // inside the right edge and is centred 4.5 px above the baseline; its fill is the team colour mixed toward white.
        Color fill = AppMapCanvas.mix(team, Color.WHITE, 0.82);
        assertEquals(fill.getRGB(), img.getRGB((560 - 12 - 3) * 2, (150 - 4) * 2));
        // Outside the box, to its right, there is no pill.
        assertEquals(p.background().getRGB(), img.getRGB((560 + 6) * 2, (150 - 4) * 2));
    }

    private static BufferedImage paintMarks(java.util.Map<String, AppMapLights.Mark> marks, java.util.List<String> trail) throws Exception {
        AppMapFile.Drawing d = AppMapFile.read(AppMapFileTest.SAMPLE).drawing("top");
        BufferedImage img = new BufferedImage(1200, 600, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = img.createGraphics();
        g.setColor(AppMapCanvas.Palette.light().background());
        g.fillRect(0, 0, 1200, 600);
        AppMapCanvas.paint(g, d, AREA, 2.0, marks, trail, AppMapCanvas.Palette.light(), java.util.Map.of());
        g.dispose();
        return img;
    }

    @Test
    void aUserIsFilledAmberAndTheOpenFilesPartKeepsTheAccent() throws Exception {
        BufferedImage img = paintMarks(java.util.Map.of(
            "orders", new AppMapLights.Mark(AppMapLights.Kind.HERE, 1, null),
            "web", new AppMapLights.Mark(AppMapLights.Kind.USER, 1, null)), java.util.List.of());
        assertEquals(AppMapCanvas.Palette.light().accentFill().getRGB(), img.getRGB(ORDERS_X, ORDERS_Y));
        assertEquals(AppMapCanvas.USER_FILL.getRGB(), img.getRGB(WEB_X, WEB_Y));
    }

    @Test
    void aBranchLightsEveryChangedPartInTheAccent() throws Exception {
        BufferedImage img = paintMarks(java.util.Map.of(
            "orders", new AppMapLights.Mark(AppMapLights.Kind.CHANGED, 1, null),
            "web", new AppMapLights.Mark(AppMapLights.Kind.CHANGED, 1, null)), java.util.List.of());
        int fill = AppMapCanvas.Palette.light().accentFill().getRGB();
        assertEquals(fill, img.getRGB(ORDERS_X, ORDERS_Y));
        assertEquals(fill, img.getRGB(WEB_X, WEB_Y));
    }

    @Test
    void theBusiestTabPartIsDarkerThanTheQuietestAndTheQuietestIsTheLightFill() throws Exception {
        BufferedImage img = paintMarks(java.util.Map.of(
            "orders", new AppMapLights.Mark(AppMapLights.Kind.HEAT, 1, null),
            "web", new AppMapLights.Mark(AppMapLights.Kind.HEAT, AppMapLights.MIN_HEAT, null)), java.util.List.of());
        Color busy = new Color(img.getRGB(ORDERS_X, ORDERS_Y)), quiet = new Color(img.getRGB(WEB_X, WEB_Y));
        assertEquals(AppMapCanvas.Palette.light().accentFill().getRGB(), quiet.getRGB());
        assertTrue(busy.getRed() + busy.getGreen() < quiet.getRed() + quiet.getGreen(), "busy " + busy + " quiet " + quiet);
    }

    @Test
    void theCurrentStepCarriesItsNumberInAnAccentDisc() throws Exception {
        // The disc is centred 22 px in from the box's top right: orders is x 40..220, y 196..256 at 1x.
        BufferedImage img = paintMarks(java.util.Map.of(
            "orders", new AppMapLights.Mark(AppMapLights.Kind.HERE, 1, "3")), java.util.List.of());
        int accent = AppMapCanvas.Palette.light().accent().getRGB();
        assertEquals(accent, img.getRGB((220 - 22 - 9) * 2, (196 + 22) * 2));
        BufferedImage none = paintMarks(java.util.Map.of(
            "orders", new AppMapLights.Mark(AppMapLights.Kind.HERE, 1, null)), java.util.List.of());
        assertNotEquals(accent, none.getRGB((220 - 22 - 9) * 2, (196 + 22) * 2));
    }
}
