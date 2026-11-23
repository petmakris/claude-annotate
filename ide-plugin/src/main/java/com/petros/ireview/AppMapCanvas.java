package com.petros.ireview;

import java.awt.*;
import java.awt.geom.AffineTransform;
import java.awt.geom.Path2D;
import java.awt.geom.Rectangle2D;
import java.awt.geom.RoundRectangle2D;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Paints one drawing of a map.json with Java2D: scaled to a rectangle, with one
 * part lit. AWT and Swing only, so a test paints it into a BufferedImage.
 *
 * What is lit: the part's box (accent fill, thick border), every shape carrying
 * an edge key that has the part at either end (in the accent), and the zone
 * that holds the box. Other shapes with a key are drawn dim. Shapes with no key
 * (title, subtitle, legend) keep their look.
 */
public final class AppMapCanvas {

    private AppMapCanvas() {}

    /** Colours of one theme. Plain values, so the overlay builds them from the IDE theme and a test from constants. */
    public record Palette(Color background, Color ink, Color muted, Color boxFill, Color line,
                          Color accent, Color accentFill, Map<String, Color> toneLine,
                          Map<String, Color> toneFill, String sansFamily) {

        public static Palette light() {
            return new Palette(new Color(0xFFFFFF), new Color(0x1F2328), new Color(0x57606A),
                new Color(0xF6F8FA), new Color(0x8C959F), new Color(0x0A58CA), new Color(0xCFE2FF),
                Map.of("blue", new Color(0x0969DA), "red", new Color(0xCF222E),
                    "green", new Color(0x1A7F37), "amber", new Color(0x9A6700)),
                Map.of("blue", new Color(0xDDF4FF), "red", new Color(0xFFEBE9),
                    "green", new Color(0xDAFBE1), "amber", new Color(0xFFF8C5)),
                "Dialog");
        }

        public static Palette dark() {
            return new Palette(new Color(0x1E1F22), new Color(0xDFE1E5), new Color(0x9DA0A8),
                new Color(0x2B2D30), new Color(0x6F737A), new Color(0x6EA8FE), new Color(0x1F3A6B),
                Map.of("blue", new Color(0x58A6FF), "red", new Color(0xFF7B72),
                    "green", new Color(0x56D364), "amber", new Color(0xE3B341)),
                Map.of("blue", new Color(0x12294A), "red", new Color(0x4A1E1C),
                    "green", new Color(0x14381F), "amber", new Color(0x3D3210)),
                "Dialog");
        }

        public Palette withSans(String family) {
            return new Palette(background, ink, muted, boxFill, line, accent, accentFill, toneLine, toneFill, family);
        }
    }

    private static final Color[] TEAM_COLOURS = {
        new Color(0x2F81F7), new Color(0xE8590C), new Color(0x2F9E44), new Color(0xAE3EC9),
        new Color(0xF08C00), new Color(0x0C8599), new Color(0xD6336C), new Color(0x5C940D),
        new Color(0x7048E8), new Color(0x862E9C)};

    /**
     * One colour per team, in order of team name, across the whole map, so a team keeps its colour on every map and on
     * the editor's pill.
     */
    public static Map<String, Color> teamColours(AppMapFile map) {
        java.util.TreeSet<String> teams = new java.util.TreeSet<>();
        for (String id : map.ownedIds()) {
            for (AppMapFile.Pill pill : map.pills(id)) if (pill.team() != null) teams.add(pill.team());
        }
        Map<String, Color> out = new java.util.LinkedHashMap<>();
        int i = 0;
        for (String t : teams) out.put(t, TEAM_COLOURS[i++ % TEAM_COLOURS.length]);
        return out;
    }

    /** A team pill drawn inside a box, at the right end of its last line of text. */
    public record Tag(String text, Color color) {}

    /** How a drawing sits in an area: scale and the top-left of the drawing in area coordinates. */
    public record Transform(double scale, double x, double y) {}

    private static final float DIM_SHAPE = 0.35f;
    private static final float DIM_TEXT = 0.7f;

    public static Transform layout(AppMapFile.Drawing d, Rectangle area, double maxScale) {
        double s = Math.min(Math.min(area.width / d.width, area.height / d.height), maxScale);
        if (!(s > 0)) s = 0.01;
        return new Transform(s, area.x + (area.width - d.width * s) / 2, area.y + (area.height - d.height * s) / 2);
    }

    public static void paint(Graphics2D g, AppMapFile.Drawing d, Rectangle area, double maxScale,
                             String litPart, Palette p) {
        paint(g, d, area, maxScale, litPart, p, Map.<String, java.util.List<Tag>>of());
    }

    /** {@code tags} maps a {@code box:<id>} key to the team pills drawn inside that box, biggest team first. */
    public static void paint(Graphics2D g0, AppMapFile.Drawing d, Rectangle area, double maxScale,
                             String litPart, Palette p, Map<String, java.util.List<Tag>> tags) {
        paint(g0, d, area, maxScale, litPart == null ? Map.of() : Map.of(litPart, new AppMapLights.Mark(AppMapLights.Kind.HERE, 1, null)),
            java.util.List.of(), p, tags);
    }

    static final Color USER_LINE = new Color(0xB86E00), USER_FILL = new Color(0xFFEFD2);

    /**
     * Paints a drawing with any number of parts lit, each by its {@link AppMapLights.Mark}: the open file's part and a
     * branch's parts in the accent, users in amber, tabs in the accent darker with more tabs, walkthrough steps grey with
     * their number. {@code trail} is the parts a walkthrough visits, joined in order by a dotted line under the boxes.
     * With no marks nothing is dimmed.
     */
    public static void paint(Graphics2D g0, AppMapFile.Drawing d, Rectangle area, double maxScale,
                             Map<String, AppMapLights.Mark> marks, java.util.List<String> trail,
                             Palette p, Map<String, java.util.List<Tag>> tags) {
        Graphics2D g = (Graphics2D) g0.create();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            g.setRenderingHint(RenderingHints.KEY_STROKE_CONTROL, RenderingHints.VALUE_STROKE_PURE);
            g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
            g.setRenderingHint(RenderingHints.KEY_FRACTIONALMETRICS, RenderingHints.VALUE_FRACTIONALMETRICS_ON);
            Transform t = layout(d, area, maxScale);
            boolean any = !marks.isEmpty();
            // Each marked box, and the boxes holding it (a slice inside a bigger box): those stay undimmed as frames.
            java.util.Map<String, Rectangle2D> boxes = new java.util.HashMap<>();
            java.util.Set<String> holders = new java.util.HashSet<>();
            java.util.Map<String, AppMapLights.Mark> ends = new java.util.HashMap<>(marks);
            for (var e : marks.entrySet()) {
                Rectangle2D b = boxOf(d, "box:" + e.getKey());
                if (b == null) continue;
                boxes.put(e.getKey(), b);
                for (String h : holders(d, e.getKey(), b)) {
                    holders.add(h);
                    ends.putIfAbsent(h, e.getValue());
                }
            }
            paintTrail(g, d, t, p, trail);
            Composite normal = g.getComposite();
            for (AppMapFile.Shape s : d.shapes) {
                boolean keyed = s.key != null;
                AppMapLights.Mark boxMark = keyed && s.key.startsWith("box:") ? marks.get(s.key.substring(4)) : null;
                Color edge = edgeColour(s, ends, p);
                boolean lit = boxMark != null || edge != null
                    || (keyed && s.key.startsWith("box:") && holders.contains(s.key.substring(4)))
                    || zoneHolds(s, boxes.values());
                boolean dim = any && keyed && !lit;
                boolean text = "text".equals(s.kind);
                g.setComposite(dim ? AlphaComposite.getInstance(AlphaComposite.SRC_OVER, text ? DIM_TEXT : DIM_SHAPE) : normal);
                switch (s.kind == null ? "" : s.kind) {
                    case "rect" -> paintRect(g, s, t, p, "box".equals(s.role) ? boxMark : null);
                    case "path" -> paintPath(g, s, s.points, t, p, edge);
                    case "line" -> paintPath(g, s, new double[][]{{s.x1, s.y1}, {s.x2, s.y2}}, t, p, edge);
                    case "circle" -> paintCircle(g, s, t, p, lit);
                    case "text" -> paintText(g, s, t, p);
                    default -> { }
                }
            }
            g.setComposite(normal);
            for (AppMapFile.Shape s : d.shapes) {
                if (s.key == null || !"rect".equals(s.kind) || !"box".equals(s.role)) continue;
                java.util.List<Tag> list = tags.get(s.key);
                if (list != null && !list.isEmpty()) paintTags(g, d, s, t, p, list);
                AppMapLights.Mark m = s.key.startsWith("box:") ? marks.get(s.key.substring(4)) : null;
                if (m != null && m.number() != null) paintNumber(g, s, t, p, m);
            }
        } finally {
            g.dispose();
        }
    }

    /** The colour an arrow is lit in: amber when it reaches a user, the accent when it touches a lit part, else null. */
    private static Color edgeColour(AppMapFile.Shape s, java.util.Map<String, AppMapLights.Mark> ends, Palette p) {
        if (s.key == null || !s.key.startsWith("edge:")) return null;
        String e = s.key.substring(5);
        int hash = e.lastIndexOf('#');
        if (hash >= 0) e = e.substring(0, hash);
        int arrow = e.indexOf("->");
        if (arrow < 0) return null;
        AppMapLights.Mark a = ends.get(e.substring(0, arrow)), b = ends.get(e.substring(arrow + 2));
        boolean aHere = a != null && a.kind() == AppMapLights.Kind.HERE, bHere = b != null && b.kind() == AppMapLights.Kind.HERE;
        // Who uses the file: the arrow between its part and a user is the one that matters.
        if ((aHere && b != null && b.kind() == AppMapLights.Kind.USER) || (bHere && a != null && a.kind() == AppMapLights.Kind.USER)) return USER_LINE;
        if (lights(a) || lights(b)) return p.accent();
        return null;
    }

    /** Arrows light around the open file's part and a branch's parts; tabs, users and past steps light no arrows. */
    private static boolean lights(AppMapLights.Mark m) {
        return m != null && (m.kind() == AppMapLights.Kind.HERE || m.kind() == AppMapLights.Kind.CHANGED);
    }

    private static boolean zoneHolds(AppMapFile.Shape s, java.util.Collection<Rectangle2D> boxes) {
        if (s.key == null || !s.key.startsWith("zone:") || !"rect".equals(s.kind)) return false;
        Rectangle2D z = new Rectangle2D.Double(s.x, s.y, s.w, s.h);
        for (Rectangle2D b : boxes) if (z.contains(b)) return true;
        return false;
    }

    /** A dotted line from the centre of each visited box to the next, painted first so the boxes cover it. */
    private static void paintTrail(Graphics2D g, AppMapFile.Drawing d, Transform t, Palette p, java.util.List<String> trail) {
        if (trail.size() < 2) return;
        Path2D.Double path = new Path2D.Double();
        boolean first = true;
        for (String id : trail) {
            Rectangle2D b = boxOf(d, "box:" + id);
            if (b == null) continue;
            double x = t.x + b.getCenterX() * t.scale, y = t.y + b.getCenterY() * t.scale;
            if (first) path.moveTo(x, y); else path.lineTo(x, y);
            first = false;
        }
        float u = (float) (2.5 * t.scale);
        g.setColor(p.accent());
        g.setStroke(new BasicStroke(u, BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND, 10f, new float[]{0.1f, u * 2.6f}, 0f));
        g.draw(path);
    }

    /** A walkthrough step's number in a disc at the top right of its box: filled for the current step. */
    private static void paintNumber(Graphics2D g, AppMapFile.Shape box, Transform t, Palette p, AppMapLights.Mark m) {
        double sc = t.scale, r = 13 * sc;
        double cx = t.x + (box.x + box.w) * sc - 22 * sc, cy = t.y + box.y * sc + 22 * sc;
        boolean now = m.kind() == AppMapLights.Kind.HERE;
        java.awt.geom.Ellipse2D.Double disc = new java.awt.geom.Ellipse2D.Double(cx - r, cy - r, 2 * r, 2 * r);
        g.setColor(now ? p.accent() : p.muted());
        g.fill(disc);
        Font f = new Font(p.sansFamily(), Font.BOLD, 1).deriveFont((float) (13 * sc));
        g.setFont(f);
        FontMetrics fm = g.getFontMetrics(f);
        g.setColor(Color.WHITE);
        g.drawString(m.number(), (float) (cx - fm.stringWidth(m.number()) / 2.0), (float) (cy + (fm.getAscent() - fm.getDescent()) / 2.0));
    }

    /** The {@code box:} key under a point, topmost first, or null. */
    public static String keyAt(AppMapFile.Drawing d, Rectangle area, double maxScale, Point pt) {
        Transform t = layout(d, area, maxScale);
        double x = (pt.x - t.x) / t.scale, y = (pt.y - t.y) / t.scale;
        List<AppMapFile.Shape> shapes = d.shapes;
        for (int i = shapes.size() - 1; i >= 0; i--) {
            AppMapFile.Shape s = shapes.get(i);
            if ("rect".equals(s.kind) && "box".equals(s.role) && s.key != null && s.key.startsWith("box:")
                && x >= s.x && x <= s.x + s.w && y >= s.y && y <= s.y + s.h) {
                return s.key;
            }
        }
        return null;
    }

    /** The area the drawing covers once laid out in {@code area}. */
    public static Rectangle bounds(AppMapFile.Drawing d, Rectangle area, double maxScale) {
        Transform t = layout(d, area, maxScale);
        return new Rectangle((int) Math.floor(t.x), (int) Math.floor(t.y),
            (int) Math.ceil(d.width * t.scale), (int) Math.ceil(d.height * t.scale));
    }

    // ---- lighting ---------------------------------------------------------

    private static Rectangle2D boxOf(AppMapFile.Drawing d, String key) {
        for (AppMapFile.Shape s : d.shapes) {
            if ("rect".equals(s.kind) && key.equals(s.key)) return new Rectangle2D.Double(s.x, s.y, s.w, s.h);
        }
        return null;
    }

    /** The ids of the boxes that hold the lit box (a slice drawn inside a bigger box), outermost or not. */
    static java.util.Set<String> holders(AppMapFile.Drawing d, String part, Rectangle2D litBox) {
        java.util.Set<String> out = new java.util.HashSet<>();
        if (litBox == null) return out;
        for (AppMapFile.Shape s : d.shapes) {
            if (!"rect".equals(s.kind) || !"box".equals(s.role) || s.key == null || !s.key.startsWith("box:")) continue;
            String id = s.key.substring(4);
            if (!id.equals(part) && new Rectangle2D.Double(s.x, s.y, s.w, s.h).contains(litBox)) out.add(id);
        }
        return out;
    }

    /** The boxes holding a part's box, biggest (outermost) first. */
    public static java.util.List<String> holdersOutermostFirst(AppMapFile.Drawing d, String part) {
        Rectangle2D box = part == null ? null : boxOf(d, "box:" + part);
        java.util.List<String> ids = new java.util.ArrayList<>(holders(d, part, box));
        java.util.Map<String, Double> area = new java.util.HashMap<>();
        for (String id : ids) { Rectangle2D r = boxOf(d, "box:" + id); area.put(id, r == null ? 0 : r.getWidth() * r.getHeight()); }
        ids.sort((x, y) -> Double.compare(area.get(y), area.get(x)));
        return ids;
    }

    // ---- shapes -----------------------------------------------------------

    private static Color toneColor(Palette p, String tone, Color plain) {
        Color c = tone == null ? null : p.toneLine().get(tone);
        return c == null ? plain : c;
    }

    private static Color fillOf(Palette p, String tone) {
        return tone == null ? null : p.toneFill().get(tone);
    }

    private static Stroke stroke(double width, boolean dashed, double scale) {
        float w = (float) (width * scale);
        if (!dashed) return new BasicStroke(w, BasicStroke.CAP_BUTT, BasicStroke.JOIN_ROUND);
        float u = (float) (4 * scale);
        return new BasicStroke(w, BasicStroke.CAP_BUTT, BasicStroke.JOIN_ROUND, 10f, new float[]{u, u * 0.75f}, 0f);
    }

    private static void paintRect(Graphics2D g, AppMapFile.Shape s, Transform t, Palette p, AppMapLights.Mark mark) {
        double sc = t.scale;
        RoundRectangle2D r = new RoundRectangle2D.Double(t.x + s.x * sc, t.y + s.y * sc, s.w * sc, s.h * sc,
            2 * s.r * sc, 2 * s.r * sc);
        boolean zone = "zone".equals(s.role);
        if (mark != null) {
            Color fill, line;
            boolean dashed = false;
            switch (mark.kind()) {
                case USER -> { fill = USER_FILL; line = USER_LINE; }
                case STEP -> { fill = p.boxFill(); line = p.muted(); dashed = true; }
                case HEAT -> { fill = mix(p.accentFill(), p.accent(), 0.5 * Math.max(0, mark.heat() - AppMapLights.MIN_HEAT) / (1 - AppMapLights.MIN_HEAT));
                               line = p.accent(); }
                default -> { fill = p.accentFill(); line = p.accent(); }
            }
            g.setColor(fill);
            g.fill(r);
            g.setColor(line);
            g.setStroke(stroke(dashed ? 2.0 : 2.5, dashed, sc));
            g.draw(r);
            return;
        }
        // A box's tone is ignored: on this map the lit part is the only colour, so a red box would read as "here".
        if (!zone) {
            g.setColor(p.boxFill());
            g.fill(r);
        }
        g.setColor(p.line());
        g.setStroke(stroke(zone ? 1.2 : 1.5, s.dashed, sc));
        g.draw(r);
    }

    private static void paintPath(Graphics2D g, AppMapFile.Shape s, double[][] pts, Transform t, Palette p, Color litColour) {
        boolean lit = litColour != null;
        if (pts == null || pts.length < 2) return;
        double sc = t.scale;
        Color base = "leader".equals(s.role) ? p.muted() : toneColor(p, s.tone, p.ink());
        Color c = lit ? litColour : base;
        Path2D.Double path = new Path2D.Double();
        for (int i = 0; i < pts.length; i++) {
            double x = t.x + pts[i][0] * sc, y = t.y + pts[i][1] * sc;
            if (i == 0) path.moveTo(x, y); else path.lineTo(x, y);
        }
        g.setColor(c);
        g.setStroke(stroke(lit ? 2.2 : 1.5, s.dashed, sc));
        g.draw(path);
        if (s.arrow) {
            double[] a = pts[pts.length - 2], b = pts[pts.length - 1];
            double ax = t.x + a[0] * sc, ay = t.y + a[1] * sc, bx = t.x + b[0] * sc, by = t.y + b[1] * sc;
            double len = Math.hypot(bx - ax, by - ay);
            if (len > 0) {
                double ux = (bx - ax) / len, uy = (by - ay) / len;
                double head = 7 * sc, half = 3.2 * sc;
                Path2D.Double tri = new Path2D.Double();
                tri.moveTo(bx, by);
                tri.lineTo(bx - ux * head - uy * half, by - uy * head + ux * half);
                tri.lineTo(bx - ux * head + uy * half, by - uy * head - ux * half);
                tri.closePath();
                g.setStroke(new BasicStroke(1f));
                g.fill(tri);
            }
        }
    }

    private static void paintCircle(Graphics2D g, AppMapFile.Shape s, Transform t, Palette p, boolean lit) {
        double sc = t.scale, r = s.r * sc;
        java.awt.geom.Ellipse2D.Double e = new java.awt.geom.Ellipse2D.Double(
            t.x + s.x * sc - r, t.y + s.y * sc - r, 2 * r, 2 * r);
        Color fill = fillOf(p, s.tone);
        g.setColor(lit ? p.accentFill() : fill != null ? fill : p.boxFill());
        g.fill(e);
        g.setColor(lit ? p.accent() : toneColor(p, s.tone, p.line()));
        g.setStroke(stroke(1.2, s.dashed, sc));
        g.draw(e);
    }

    static final double TAG_H = 18, TAG_PAD = 7, TAG_GAP = 5, TAG_FONT = 10.5;

    /** Team pills, right-aligned inside the box on its last line of text (or its first line when the box has one). */
    private static void paintTags(Graphics2D g, AppMapFile.Drawing d, AppMapFile.Shape box, Transform t, Palette p,
                                  java.util.List<Tag> tags) {
        double sc = t.scale;
        double baseline = -1;
        AppMapFile.Shape last = null;
        for (AppMapFile.Shape s : d.shapes) {
            if (!"text".equals(s.kind) || !box.key.equals(s.key)) continue;
            if (s.y < box.y || s.y > box.y + box.h) continue;
            if (s.y > baseline) { baseline = s.y; last = s; }
        }
        // The build ends each part's box with a blank line: then the pills have that row to themselves, from its left.
        boolean ownRow = last != null && isBlank(last);
        double h = TAG_H * sc;
        double cy = baseline < 0 ? box.y * sc + t.y + h : t.y + (baseline - 4.5) * sc;
        Font f = new Font(p.sansFamily(), Font.BOLD, 1).deriveFont((float) (TAG_FONT * sc));
        g.setFont(f);
        FontMetrics fm = g.getFontMetrics(f);
        double x = ownRow ? t.x + last.x * sc : t.x + (box.x + box.w) * sc - 12 * sc;
        for (Tag tag : tags) {
            double w = fm.getStringBounds(tag.text(), g).getWidth() + 2 * TAG_PAD * sc;
            if (!ownRow) x -= w;
            RoundRectangle2D pill = new RoundRectangle2D.Double(x, cy - h / 2, w, h, h, h);
            g.setColor(mix(tag.color(), Color.WHITE, 0.82));
            g.fill(pill);
            g.setColor(mix(tag.color(), Color.WHITE, 0.35));
            g.setStroke(new BasicStroke((float) Math.max(1, sc)));
            g.draw(pill);
            g.setColor(mix(tag.color(), Color.BLACK, 0.45));
            g.drawString(tag.text(), (float) (x + TAG_PAD * sc), (float) (cy + (fm.getAscent() - fm.getDescent()) / 2.0));
            x += ownRow ? w + TAG_GAP * sc : -TAG_GAP * sc;
        }
    }

    /** A text line with nothing to read: only spaces, including the no-break space the build uses. */
    static boolean isBlank(AppMapFile.Shape s) {
        if (s.runs == null) return true;
        for (AppMapFile.Run r : s.runs) if (r.text != null && !r.text.replace('\u00a0', ' ').isBlank()) return false;
        return true;
    }

    static Color mix(Color a, Color b, double towardB) {
        return new Color(
            (int) Math.round(a.getRed() + (b.getRed() - a.getRed()) * towardB),
            (int) Math.round(a.getGreen() + (b.getGreen() - a.getGreen()) * towardB),
            (int) Math.round(a.getBlue() + (b.getBlue() - a.getBlue()) * towardB));
    }

    // ---- text -------------------------------------------------------------

    private static volatile Boolean monoAvailable;

    private static boolean monoAvailable() {
        Boolean b = monoAvailable;
        if (b == null) {
            b = java.util.Arrays.asList(GraphicsEnvironment.getLocalGraphicsEnvironment()
                .getAvailableFontFamilyNames()).contains("JetBrains Mono");
            monoAvailable = b;
        }
        return b;
    }

    private static Font font(Palette p, AppMapFile.Shape s, boolean mono, double scale) {
        int style = s.weight >= 600 ? Font.BOLD : Font.PLAIN;
        Font base = mono
            ? new Font(monoAvailable() ? "JetBrains Mono" : Font.MONOSPACED, style, 1)
            : new Font(p.sansFamily(), style, 1);
        return base.deriveFont((float) (s.size * scale * (mono ? 0.92 : 1.0)));
    }

    private static void paintText(Graphics2D g, AppMapFile.Shape s, Transform t, Palette p) {
        if (s.runs == null || s.runs.isEmpty()) return;
        double sc = t.scale;
        boolean upper = "column".equals(s.role);
        double width = 0;
        for (AppMapFile.Run r : s.runs) {
            width += g.getFontMetrics(font(p, s, r.mono, sc)).getStringBounds(text(r, upper), g).getWidth();
        }
        double x = t.x + s.x * sc, y = t.y + s.y * sc;
        if ("middle".equals(s.anchor)) x -= width / 2;
        else if ("end".equals(s.anchor)) x -= width;
        boolean strong = "title".equals(s.role) || "name".equals(s.role);
        Color plain = toneColor(p, s.tone, strong ? p.ink() : p.muted());
        for (AppMapFile.Run r : s.runs) {
            Font f = font(p, s, r.mono, sc);
            g.setFont(f);
            // Code names (module names, `advisory`) are drawn in the ink colour, so small mono text stays readable.
            g.setColor(r.mono ? p.ink() : plain);
            String str = text(r, upper);
            g.drawString(str, (float) x, (float) y);
            x += g.getFontMetrics(f).getStringBounds(str, g).getWidth();
        }
    }

    private static String text(AppMapFile.Run r, boolean upper) {
        String s = r.text == null ? "" : r.text;
        return upper ? s.toUpperCase(Locale.ROOT) : s;
    }
}
