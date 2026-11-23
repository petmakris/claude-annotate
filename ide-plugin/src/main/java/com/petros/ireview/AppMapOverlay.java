package com.petros.ireview;

import com.intellij.icons.AllIcons;
import com.intellij.util.ui.JBUI;
import com.intellij.util.ui.UIUtil;

import javax.swing.*;
import java.awt.*;
import java.awt.event.ComponentAdapter;
import java.awt.event.ComponentEvent;
import java.awt.event.KeyEvent;
import java.awt.event.MouseAdapter;
import java.awt.event.MouseEvent;
import java.awt.geom.RoundRectangle2D;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;

/**
 * The app map over the IDE window: a plain child of the window's layered pane at
 * POPUP_LAYER (not a JBPopup, so focus changes never close it, as with
 * {@link WalkthroughHud}). It dims the IDE and paints a header row, the drawing
 * and a footer of buttons. Keys are read by {@link AppMapActions}, which calls
 * {@link #enter}, {@link #back} and {@link #close}.
 */
public final class AppMapOverlay extends JComponent {

    /**
     * What the overlay shows: a map, or a message when there is none or it cannot be read. {@code sources} gives the
     * files of the other modes (null with no map); {@code start} is the mode it opens in.
     */
    public record Input(String fileName, AppMapFile map, String message,
                        AppMapFile.Place place, List<String> owners, String module,
                        Sources sources, Mode start) {
        public Input(String fileName, AppMapFile map, String message, AppMapFile.Place place, List<String> owners, String module) {
            this(fileName, map, message, place, owners, module, null, Mode.FILE);
        }
    }

    /** What the map lights: the open file's part, or one of the views the user asked for (23 November 2026). */
    public enum Mode {
        FILE("This file", 'F', AllIcons.General.Locate),
        BRANCH("Branch", 'B', AllIcons.Vcs.Branch),
        TABS("Open tabs", 'T', AllIcons.FileTypes.Any_type),
        USERS("Used by", 'U', AllIcons.Actions.Find),
        WALK("Walkthrough", 'W', AllIcons.Actions.Play_forward);

        final String label; final char key; final Icon icon;
        Mode(String label, char key, Icon icon) { this.label = label; this.key = key; this.icon = icon; }

        public static Mode forKey(int keyCode) {
            for (Mode m : values()) if (KeyEvent.getExtendedKeyCodeForChar(m.key) == keyCode) return m;
            return null;
        }
    }

    /**
     * A mode's files as places on the map. {@code title} heads the header while the mode shows; {@code note} is said
     * after it (no changes, nothing found, why it failed). {@code current} is the walkthrough's step, 0-based.
     */
    public record Result(List<AppMapFile.Place> places, int current, String title, String note) {
        public static Result note(String title, String note) { return new Result(List.of(), -1, title, note); }
    }

    /** Reads a mode's files when the mode is first picked. {@code done} runs on the UI thread, now or later. */
    public interface Sources {
        boolean has(Mode m);
        /** The header while the files are being read. */
        String loading(Mode m);
        void load(Mode m, java.util.function.Consumer<Result> done);
    }


    private static final String NO_SUB_PART = "On no sub-part";

    private final Input in;
    private final Runnable onClose;
    private final JLayeredPane host;
    private final ComponentAdapter resizer;

    private String detailId;            // null while the top map shows
    private Mode mode;
    private final Map<Mode, Result> results = new java.util.EnumMap<>(Mode.class);
    private boolean closed;

    // Filled by layoutParts(), read by paint and by the mouse.
    private Rectangle drawArea = new Rectangle();
    private Rectangle drawn = new Rectangle();
    private final List<Btn> buttons = new ArrayList<>();

    private final class Btn {
        final String label; final Icon icon; final Runnable run; final boolean on; Rectangle r = new Rectangle();
        Btn(String label, Icon icon, boolean on, Runnable run) { this.label = label; this.icon = icon; this.on = on; this.run = run; }
    }

    public AppMapOverlay(JLayeredPane host, Input in, Runnable onClose) {
        this.host = host;
        this.in = in;
        this.onClose = onClose;
        this.mode = in.sources() != null && in.start() != null && in.sources().has(in.start()) ? in.start() : Mode.FILE;
        setOpaque(true);
        MouseAdapter mouse = new MouseAdapter() {
            @Override public void mousePressed(MouseEvent e) { click(e.getPoint()); e.consume(); }
            @Override public void mouseReleased(MouseEvent e) { e.consume(); }
            @Override public void mouseClicked(MouseEvent e) { e.consume(); }
        };
        addMouseListener(mouse);
        addMouseWheelListener(wheel -> wheel.consume());
        resizer = new ComponentAdapter() {
            @Override public void componentResized(ComponentEvent e) { setBounds(0, 0, host.getWidth(), host.getHeight()); }
        };
    }

    /** Shows a mode, reading its files the first time it is picked. */
    public void mode(Mode m) {
        if (m == null || in.map() == null || in.sources() == null || !in.sources().has(m)) return;
        mode = m;
        if (!results.containsKey(m)) {
            in.sources().load(m, r -> {
                if (closed) return;
                results.put(m, r);
                repaint();
            });
        }
        repaint();
    }

    public void open() {
        host.add(this, JLayeredPane.POPUP_LAYER);
        if (mode != Mode.FILE) { Mode m = mode; mode = Mode.FILE; mode(m); }
        host.addComponentListener(resizer);
        setBounds(0, 0, host.getWidth(), host.getHeight());
        host.revalidate();
        host.repaint();
    }

    public void close() {
        closed = true;
        host.removeComponentListener(resizer);
        host.remove(this);
        host.repaint();
        onClose.run();
    }

    /** Enter: open the detail map of the file's part when it has one. */
    public void enter() {
        if (in.map() == null || detailId != null || in.place() == null) return;
        AppMapFile.Place p = in.place();
        if (p.part() != null && p.hasDetail() && in.map().drawing(p.part()) != null) showDetail(p.part());
    }

    /** Backspace or Back: from a detail map to the top map. */
    public void back() {
        if (detailId == null) return;
        detailId = null;
        repaint();
    }

    public boolean inDetail() { return detailId != null; }

    private void showDetail(String id) {
        detailId = id;
        repaint();
    }

    private void click(Point pt) {
        layoutParts();
        for (Btn b : buttons) {
            if (b.r.contains(pt)) { b.run.run(); return; }
        }
        if (in.map() != null && drawn.contains(pt)) {
            String key = AppMapCanvas.keyAt(current(), drawArea, maxScale(), pt);
            if (key != null && detailId == null) {
                String id = key.substring("box:".length());
                if (in.map().detailIds().contains(id) && in.map().drawing(id) != null) showDetail(id);
            }
            return;
        }
        close();
    }

    // ---- state ------------------------------------------------------------

    private AppMapFile.Drawing current() {
        return in.map().drawing(detailId == null ? "top" : detailId);
    }

    /** The drawing may grow to twice its built size, so a wide screen is filled. */
    private double maxScale() { return JBUI.scale(2f); }

    /** What the drawing in front lights in the current mode. Nothing while a mode's files are still being read. */
    private Map<String, AppMapLights.Mark> marks() {
        if (mode == Mode.FILE) return AppMapLights.here(in.place(), detailId);
        Result r = results.get(mode);
        if (r == null) return Map.of();
        return switch (mode) {
            case BRANCH -> AppMapLights.changed(r.places(), detailId);
            case TABS -> AppMapLights.tabs(r.places(), detailId);
            case USERS -> AppMapLights.users(in.place(), r.places(), detailId);
            case WALK -> AppMapLights.steps(r.places(), r.current(), detailId);
            default -> Map.of();
        };
    }

    private List<String> trail() {
        Result r = results.get(mode);
        return mode == Mode.WALK && r != null ? AppMapLights.trail(r.places(), detailId) : List.of();
    }

    private boolean noSubPart() {
        AppMapFile.Place p = in.place();
        return detailId != null && p != null && detailId.equals(p.part()) && p.subPart() == null;
    }

    private AppMapCanvas.Palette palette() {
        String sans = UIUtil.getLabelFont().getFamily();
        // Always light, whatever the IDE theme: the user asked for a light map (23 November 2026).
        return AppMapCanvas.Palette.light().withSans(sans);
    }

    private static String day(String stamp) { return stamp.length() >= 10 ? stamp.substring(0, 10) : stamp; }

    private String partTitle(String id) {
        if (id == null || in.map() == null) return id;
        for (AppMapFile.Shape s : in.map().drawing("top").shapes) {
            if (("box:" + id).equals(s.key) && "text".equals(s.kind) && "name".equals(s.role) && s.runs != null) {
                StringBuilder sb = new StringBuilder();
                for (AppMapFile.Run r : s.runs) sb.append(r.text);
                return sb.toString().trim();
            }
        }
        return id;
    }

    private String placeText() {
        AppMapFile.Place p = in.place();
        if (p == null || p.part() == null) return "Not on the map";
        return placeOf(p);
    }

    private String placeOf(AppMapFile.Place p) {
        String top = partTitle(p.part());
        // A slice drawn inside a bigger box is named with that box first, outermost first: "Web API › Reports".
        AppMapFile.Drawing topMap = in.map().drawing("top");
        java.util.List<String> holders = new java.util.ArrayList<>(AppMapCanvas.holdersOutermostFirst(topMap, p.part()));
        if (!holders.isEmpty()) {
            StringBuilder sb = new StringBuilder();
            for (String h : holders) sb.append(partTitle(h)).append(" › ");
            top = sb + top;
        }
        if (p.subPart() == null) return top;
        String sub = p.subPart();
        AppMapFile.Drawing d = in.map().drawing(p.part());
        if (d != null) {
            for (AppMapFile.Shape s : d.shapes) {
                if (("box:" + sub).equals(s.key) && "text".equals(s.kind) && "name".equals(s.role) && s.runs != null) {
                    StringBuilder sb = new StringBuilder();
                    for (AppMapFile.Run r : s.runs) sb.append(r.text);
                    sub = sb.toString().trim();
                    break;
                }
            }
        }
        return top + " › " + sub;
    }

    // ---- layout -----------------------------------------------------------

    private static Font font(float size, boolean bold) {
        Font f = JBUI.Fonts.label(size);
        return bold ? f.deriveFont(Font.BOLD) : f;
    }

    /**
     * The overlay's chrome is one row at the very top: on the Mac it sits in the title-bar strip, right of the window
     * buttons. Everything below it, less a thin margin, is the drawing's (the user asked for the space, 23 November 2026).
     */
    private static final int HEADER_H = 40, MARGIN = 10, MAC_BUTTONS_W = 84;

    private int headerLeft() {
        return JBUI.scale(com.intellij.openapi.util.SystemInfo.isMac ? MAC_BUTTONS_W : MARGIN + 6);
    }

    private void layoutParts() {
        int w = getWidth(), h = getHeight();
        int margin = JBUI.scale(MARGIN), header = JBUI.scale(HEADER_H);
        drawArea = new Rectangle(margin, header, Math.max(1, w - 2 * margin), Math.max(1, h - header - margin));
        if (in.map() != null && current() != null) {
            // Sit the drawing right under the header: any height it cannot use is left at the bottom, not split.
            double scale = AppMapCanvas.layout(current(), drawArea, maxScale()).scale();
            int used = (int) Math.ceil(current().height * scale);
            if (used < drawArea.height) drawArea = new Rectangle(drawArea.x, drawArea.y, drawArea.width, used);
        }
        if (in.map() != null) drawn = AppMapCanvas.bounds(current(), drawArea, maxScale());
        else drawn = new Rectangle();

        buttons.clear();
        if (in.map() != null && in.sources() != null) {
            for (Mode m : Mode.values()) {
                if (in.sources().has(m)) buttons.add(new Btn(m.label, m.icon, m == mode, () -> mode(m)));
            }
        }
        if (in.map() != null && detailId != null) buttons.add(new Btn("Back", AllIcons.Actions.Back, false, this::back));
        buttons.add(new Btn("Close", AllIcons.Actions.Close, false, this::close));
        Graphics2D probe = (Graphics2D) (getGraphics() != null ? getGraphics() : new java.awt.image.BufferedImage(1, 1, 1).getGraphics());
        FontMetrics fm = probe.getFontMetrics(font(13f, false));
        int gap = JBUI.scale(8), bh = JBUI.scale(26), pad = JBUI.scale(10);
        int x = w - JBUI.scale(MARGIN + 6), y = (header - bh) / 2;
        for (int i = buttons.size() - 1; i >= 0; i--) {
            Btn b = buttons.get(i);
            int bw = pad * 2 + b.icon.getIconWidth() + JBUI.scale(6) + fm.stringWidth(b.label);
            x -= bw;
            b.r = new Rectangle(x, y, bw, bh);
            x -= gap;
        }
        probe.dispose();
    }

    // ---- painting ---------------------------------------------------------

    @Override protected void paintComponent(Graphics g0) {
        Graphics2D g = (Graphics2D) g0.create();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
            AppMapCanvas.Palette p = palette();
            Color bg = p.background();
            g.setColor(bg); // fully opaque: nothing of the IDE shows through (the user's choice, 23 November 2026)
            g.fillRect(0, 0, getWidth(), getHeight());
            layoutParts();
            if (in.map() == null) paintMessage(g, p); else paintMap(g, p);
            paintButtons(g, p);
        } finally {
            g.dispose();
        }
    }

    /** Draws text vertically centred on {@code centreY}; returns the x after it. */
    private static int drawCentred(Graphics2D g, String text, Font f, Color c, int x, int centreY) {
        g.setFont(f);
        g.setColor(c);
        FontMetrics fm = g.getFontMetrics();
        g.drawString(text, x, centreY + (fm.getAscent() - fm.getDescent()) / 2);
        return x + fm.stringWidth(text);
    }

    private void paintMessage(Graphics2D g, AppMapCanvas.Palette p) {
        g.setFont(font(15f, false));
        g.setColor(p.ink());
        FontMetrics fm = g.getFontMetrics();
        String text = in.message();
        int tw = fm.stringWidth(text);
        g.drawString(text, Math.max(JBUI.scale(24), (getWidth() - tw) / 2), getHeight() / 2);
    }

    /**
     * Where the header starts. On the Mac the IDE draws its window buttons and toolbar inside the window, under this
     * overlay, so the header starts below them.
     */
    private void paintMap(Graphics2D g, AppMapCanvas.Palette p) {
        // One row: file name, where it sits, its module and owners; the build date sits left of the buttons.
        int x = headerLeft();
        int base = JBUI.scale(HEADER_H) / 2;
        Font bold = font(14f, true), plain = font(13f, false);
        Font mono = new Font("JetBrains Mono", Font.PLAIN, 1).deriveFont((float) JBUI.scale(12.5f));
        int right = buttons.isEmpty() ? getWidth() - JBUI.scale(MARGIN) : buttons.get(0).r.x;
        Shape clip = g.getClip();
        g.clipRect(0, 0, right - JBUI.scale(14), JBUI.scale(HEADER_H));
        if (mode == Mode.FILE) {
            x = drawCentred(g, in.fileName() == null ? "No file open" : in.fileName(), bold, p.ink(), x, base) + JBUI.scale(14);
            x = drawCentred(g, in.place() == null ? "Not on the map" : placeText(), plain,
                in.place() != null && in.place().part() != null ? p.accent() : p.muted(), x, base) + JBUI.scale(14);
            if (in.module() != null) {
                x = drawCentred(g, "Module ", plain, p.muted(), x, base);
                x = drawCentred(g, in.module(), mono, p.ink(), x, base) + JBUI.scale(14);
            }
            if (in.place() != null) {
                x = drawCentred(g, in.owners().isEmpty() ? "No owner" : String.join("  ", in.owners()), plain, p.muted(), x, base) + JBUI.scale(14);
            }
        } else {
            Result r = results.get(mode);
            String title = r == null ? in.sources().loading(mode) : r.title();
            x = drawCentred(g, title == null ? mode.label : title, bold, p.ink(), x, base) + JBUI.scale(14);
            if (r != null && r.note() != null) x = drawCentred(g, r.note(), plain, p.muted(), x, base) + JBUI.scale(14);
        }
        String built = in.map().builtAt().isEmpty() ? "" : "Map built " + day(in.map().builtAt());
        Font small = font(12f, false);
        int bw = g.getFontMetrics(small).stringWidth(built);
        if (x + bw < right - JBUI.scale(14)) drawCentred(g, built, small, p.muted(), right - JBUI.scale(14) - bw, base);
        g.setClip(clip);

        AppMapCanvas.paint(g, current(), drawArea, maxScale(), marks(), trail(), p, tagsOf(current()));
        if (mode == Mode.FILE && noSubPart()) {
            g.setFont(font(14f, true));
            String note = NO_SUB_PART;
            int nw = g.getFontMetrics().stringWidth(note) + JBUI.scale(24), nh = JBUI.scale(28);
            int nx = drawArea.x + (drawArea.width - nw) / 2, ny = drawArea.y;
            g.setColor(p.accentFill());
            g.fill(new RoundRectangle2D.Double(nx, ny, nw, nh, 14, 14));
            g.setColor(p.ink());
            g.drawString(note, nx + JBUI.scale(12), ny + (nh + g.getFontMetrics().getAscent() - g.getFontMetrics().getDescent()) / 2);
        }
    }

    private Map<String, Color> teamColours() { return AppMapCanvas.teamColours(in.map()); }


    /** The team pills of every box on a drawing; files no CODEOWNERS rule covers get a grey "No owner" pill. */
    private Map<String, List<AppMapCanvas.Tag>> tagsOf(AppMapFile.Drawing d) {
        Map<String, Color> colours = teamColours();
        Map<String, List<AppMapCanvas.Tag>> out = new LinkedHashMap<>();
        for (AppMapFile.Shape s : d.shapes) {
            if (!"rect".equals(s.kind) || !"box".equals(s.role) || s.key == null || !s.key.startsWith("box:")) continue;
            List<AppMapCanvas.Tag> tags = new ArrayList<>();
            for (AppMapFile.Pill pill : in.map().pills(s.key.substring(4))) {
                Color c = pill.team() == null ? palette().muted() : colours.getOrDefault(pill.team(), palette().muted());
                tags.add(new AppMapCanvas.Tag(pill.label(), c));
            }
            if (!tags.isEmpty()) out.put(s.key, tags);
        }
        return out;
    }

    private void paintButtons(Graphics2D g, AppMapCanvas.Palette p) {
        g.setFont(font(13f, false));
        FontMetrics fm = g.getFontMetrics();
        for (Btn b : buttons) {
            Rectangle r = b.r;
            g.setColor(b.on ? p.accentFill() : p.boxFill());
            g.fill(new RoundRectangle2D.Double(r.x, r.y, r.width, r.height, 10, 10));
            g.setColor(b.on ? p.accent() : p.line());
            g.draw(new RoundRectangle2D.Double(r.x + 0.5, r.y + 0.5, r.width - 1, r.height - 1, 10, 10));
            int ix = r.x + JBUI.scale(12);
            com.intellij.openapi.util.IconLoader.getDarkIcon(b.icon, false).paintIcon(this, g, ix, r.y + (r.height - b.icon.getIconHeight()) / 2);
            g.setColor(p.ink());
            g.drawString(b.label, ix + b.icon.getIconWidth() + JBUI.scale(6),
                r.y + (r.height + fm.getAscent() - fm.getDescent()) / 2);
        }
    }
}
