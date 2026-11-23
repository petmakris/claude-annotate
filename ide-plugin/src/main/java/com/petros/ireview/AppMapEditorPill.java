package com.petros.ireview;

import com.intellij.openapi.application.ApplicationManager;
import com.intellij.openapi.application.ModalityState;
import com.intellij.openapi.diagnostic.Logger;
import com.intellij.openapi.editor.Editor;
import com.intellij.openapi.editor.EditorKind;
import com.intellij.openapi.editor.event.EditorFactoryEvent;
import com.intellij.openapi.editor.event.EditorFactoryListener;
import com.intellij.openapi.editor.impl.EditorImpl;
import com.intellij.openapi.fileEditor.FileDocumentManager;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.vfs.VirtualFile;
import com.intellij.util.ui.JBUI;
import org.jetbrains.annotations.NotNull;

import javax.swing.*;
import java.awt.*;
import java.awt.event.MouseAdapter;
import java.awt.event.MouseEvent;
import java.awt.geom.RoundRectangle2D;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * A pill at the top right of every editor whose file is on an app map: the file's build module and its CODEOWNERS
 * teams, coloured as on the map. The part of the app shows only on the map (the user's choice, 23 November 2026); a
 * click on the pill opens it. Drawn on a see-through layer the editor sizes to itself ({@link EditorImpl#addLayer}),
 * which takes the mouse only inside the pill.
 */
public final class AppMapEditorPill implements EditorFactoryListener {

    private static final Logger LOG = Logger.getInstance(AppMapEditorPill.class);

    /** What one pill says: the module (may be null) and the teams, each a label and a colour. */
    record Info(String module, List<AppMapCanvas.Tag> teams) {}

    @Override public void editorCreated(@NotNull EditorFactoryEvent event) {
        Editor editor = event.getEditor();
        if (!(editor instanceof EditorImpl impl) || editor.getEditorKind() != EditorKind.MAIN_EDITOR) return;
        Project project = editor.getProject();
        VirtualFile file = FileDocumentManager.getInstance().getFile(editor.getDocument());
        if (project == null || file == null || !file.isInLocalFileSystem() || file.getParent() == null) return;
        ApplicationManager.getApplication().executeOnPooledThread(() -> {
            Info info;
            try {
                info = infoFor(file);
            } catch (RuntimeException e) {
                LOG.debug("No app map pill for " + file.getPath(), e);
                return;
            }
            if (info == null) return;
            ApplicationManager.getApplication().invokeLater(() -> {
                if (!editor.isDisposed()) impl.addLayer(new Pill(project, file, info), JLayeredPane.PALETTE_LAYER);
            }, ModalityState.any());
        });
    }

    /** The pill for a file, or null when the file is on no map. */
    static Info infoFor(VirtualFile file) {
        AppMapStore.Found f;
        try {
            f = AppMapActions.STORE.find(Path.of(file.getParent().getPath())).orElse(null);
        } catch (AppMapFile.Unreadable u) {
            return null;
        }
        if (f == null) return null;
        String rel = AppMapActions.repoRelative(f.repoRoot(), file.getPath());
        if (rel == null) return null;
        AppMapFile map = f.map();
        String module = map.module(rel, map.repoNameFor(f.remote()));
        return new Info(module, teams(map, CodeOwners.at(f.repoRoot()).owners(rel)));
    }

    /** The file's teams as pills, coloured as on the map; a file no CODEOWNERS rule covers gets the grey "No owner". */
    static List<AppMapCanvas.Tag> teams(AppMapFile map, List<String> owners) {
        Map<String, Color> colours = AppMapCanvas.teamColours(map);
        Color grey = AppMapCanvas.Palette.light().muted();
        List<AppMapCanvas.Tag> out = new ArrayList<>();
        for (String team : owners) {
            if (out.size() == 3) break;
            out.add(new AppMapCanvas.Tag(map.label(team), colours.getOrDefault(team, grey)));
        }
        if (out.isEmpty()) out.add(new AppMapCanvas.Tag(AppMapFile.NO_OWNER, grey));
        return out;
    }

    private static final class Pill extends JComponent {
        private final Info info;
        private Rectangle pill = new Rectangle();

        Pill(Project project, VirtualFile file, Info info) {
            this.info = info;
            setOpaque(false);
            setToolTipText("Open the app map (⇧⌘M)");
            setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
            addMouseListener(new MouseAdapter() {
                @Override public void mouseClicked(MouseEvent e) {
                    if (pill.contains(e.getPoint())) AppMapActions.open(project, file);
                }
            });
        }

        /** Only the pill takes the mouse; the code under the rest of the layer stays clickable. */
        @Override public boolean contains(int x, int y) { return pill.contains(x, y); }

        private static Font mono(float size) {
            return new Font("JetBrains Mono", Font.PLAIN, 1).deriveFont((float) JBUI.scale(size));
        }

        private static Font tagFont() { return JBUI.Fonts.label(10.5f).asBold(); }

        @Override protected void paintComponent(Graphics g0) {
            Graphics2D g = (Graphics2D) g0.create();
            try {
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
                g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
                int pad = JBUI.scale(10), gap = JBUI.scale(6), h = JBUI.scale(24), tagH = JBUI.scale(17), tagPad = JBUI.scale(7);
                FontMetrics fmMono = g.getFontMetrics(mono(12f)), fmTag = g.getFontMetrics(tagFont());
                int w = pad * 2;
                if (info.module() != null) w += fmMono.stringWidth(info.module()) + gap;
                for (AppMapCanvas.Tag t : info.teams()) w += fmTag.stringWidth(t.text()) + 2 * tagPad + gap;
                w -= gap;
                pill = new Rectangle(anchorRight() - w, anchorCentre() - h / 2, w, h);

                RoundRectangle2D shape = new RoundRectangle2D.Double(pill.x, pill.y, pill.width, pill.height, h, h);
                g.setColor(new Color(0, 0, 0, 60));
                g.fill(new RoundRectangle2D.Double(pill.x, pill.y + JBUI.scale(2), pill.width, pill.height, h, h));
                g.setColor(new Color(0xF6F8FA));
                g.fill(shape);
                g.setColor(new Color(0xC8D1DC));
                g.draw(shape);

                int x = pill.x + pad, cy = pill.y + h / 2;
                if (info.module() != null) {
                    g.setFont(mono(12f));
                    g.setColor(new Color(0x1F2328));
                    g.drawString(info.module(), x, cy + (fmMono.getAscent() - fmMono.getDescent()) / 2);
                    x += fmMono.stringWidth(info.module()) + gap;
                }
                g.setFont(tagFont());
                for (AppMapCanvas.Tag t : info.teams()) {
                    int tw = fmTag.stringWidth(t.text()) + 2 * tagPad;
                    RoundRectangle2D tag = new RoundRectangle2D.Double(x, cy - tagH / 2.0, tw, tagH, tagH, tagH);
                    g.setColor(AppMapCanvas.mix(t.color(), Color.WHITE, 0.82));
                    g.fill(tag);
                    g.setColor(AppMapCanvas.mix(t.color(), Color.WHITE, 0.35));
                    g.draw(tag);
                    g.setColor(AppMapCanvas.mix(t.color(), Color.BLACK, 0.45));
                    g.drawString(t.text(), x + tagPad, cy + (fmTag.getAscent() - fmTag.getDescent()) / 2);
                    x += tw + gap;
                }
            } finally {
                g.dispose();
            }
        }

        /**
         * The editor's own widget at the top right (the inspection counts) sits in the same layered pane at y 0: the
         * pill goes left of it, on its row. Without one, the pill sits in the corner, clear of the scrollbar.
         */
        private Component statusWidget() {
            Container parent = getParent();
            if (parent == null) return null;
            for (Component c : parent.getComponents()) {
                if (c == this || !c.isVisible() || c instanceof JScrollPane || c instanceof JScrollBar) continue;
                Rectangle b = c.getBounds();
                if (b.y == 0 && b.width > 0 && b.height > 0 && b.width < getWidth() / 2 && b.x + b.width >= getWidth() - JBUI.scale(40)) return c;
            }
            return null;
        }

        private int anchorRight() {
            Component s = statusWidget();
            if (s != null) return s.getX() - JBUI.scale(8);
            return getWidth() - JBUI.scale(14 + 10);
        }

        private int anchorCentre() {
            Component s = statusWidget();
            int h = JBUI.scale(24);
            if (s != null) return Math.max(h / 2 + JBUI.scale(4), s.getY() + s.getHeight() / 2);
            return JBUI.scale(8) + h / 2;
        }
    }
}
