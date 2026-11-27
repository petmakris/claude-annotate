package promo.driver;

import com.intellij.ide.AppLifecycleListener;
import com.intellij.openapi.application.ApplicationManager;
import com.intellij.openapi.fileEditor.OpenFileDescriptor;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.project.ProjectManager;
import com.intellij.openapi.vfs.LocalFileSystem;
import com.intellij.openapi.vfs.VirtualFile;
import com.intellij.openapi.wm.WindowManager;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import javax.swing.*;
import java.awt.*;
import java.awt.event.InputEvent;
import java.awt.event.KeyEvent;
import java.awt.event.MouseEvent;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.List;

/**
 * Test-only driver for the README clip. Listens on 127.0.0.1:$PROMO_DRIVER_PORT and posts
 * synthetic AWT events into the IDE's own event queue, so the real shortcuts and clicks
 * reach the real UI without touching the OS mouse or keyboard.
 *
 *   /frame?x=&y=&w=&h=      move and size the project frame (points)
 *   /open?file=&line=       open a project file at a 1-based line
 *   /action?id=[&frame=1|&focus=1]  run an action by id (what its key runs) in the selected
 *                           editor's context, the frame's, or the focus owner's
 *   /key?code=&mods=        one key press (java.awt.event.KeyEvent VK code, InputEvent mods)
 *   /type?text=             type text into the focus owner
 *   /click?x=&y=[&count=]   click at window coordinates (points) of the active IDE window
 *   /move?x=&y=             move the pointer there (hover)
 *   /settext?text=          set the text of the top window's text field (a background app
 *                           gets no key events, so typing is shown as the text growing)
 *   /button?text=           press the showing button with this text
 *   /findline?text=         scroll the showing editor line holding text to the middle; answers
 *                           "gutterX gutterWidth lineY" in frame points
 *   /closepopups            close every open popup (what Escape does)
 *   /focus[?set=1]          the active window and focus owner; set=1 focuses the frame first
 *   /data                   the focus owner and the file its data context names
 *   /smart                  "smart" once indexing is done, else "dumb"
 *   /keymap?name=           make this keymap the active one
 *   /shortcut?id=           the active keymap's name and the action's shortcuts in it
 *   /windows                list showing windows with bounds
 */
public final class Driver implements AppLifecycleListener {

    @Override
    public void appStarted() {
        String port = System.getenv("PROMO_DRIVER_PORT");
        if (port == null) return;
        try {
            HttpServer s = HttpServer.create(new InetSocketAddress("127.0.0.1", Integer.parseInt(port)), 0);
            s.createContext("/", Driver::handle);
            s.start();
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    private static void handle(HttpExchange ex) {
        String out;
        int status = 200;
        try {
            Map<String, String> q = query(ex.getRequestURI().getRawQuery());
            String path = ex.getRequestURI().getPath();
            out = onEdt(() -> run(path, q));
        } catch (Throwable t) {
            status = 500;
            out = t.toString();
        }
        try {
            byte[] b = out.getBytes(StandardCharsets.UTF_8);
            ex.sendResponseHeaders(status, b.length);
            try (OutputStream os = ex.getResponseBody()) { os.write(b); }
        } catch (Exception ignored) { }
    }

    private interface Job { String run() throws Exception; }

    private static String onEdt(Job job) throws Exception {
        String[] res = new String[1];
        Exception[] err = new Exception[1];
        // any(): the calls must also run while a modal dialog of the IDE is open.
        ApplicationManager.getApplication().invokeAndWait(() -> {
            try { res[0] = job.run(); } catch (Exception e) { err[0] = e; }
        }, com.intellij.openapi.application.ModalityState.any());
        if (err[0] != null) throw err[0];
        return res[0];
    }

    private static Map<String, String> query(String raw) {
        Map<String, String> m = new HashMap<>();
        if (raw == null) return m;
        for (String p : raw.split("&")) {
            int i = p.indexOf('=');
            if (i < 0) m.put(p, "");
            else m.put(p.substring(0, i), URLDecoder.decode(p.substring(i + 1), StandardCharsets.UTF_8));
        }
        return m;
    }

    private static Project project() {
        Project[] ps = ProjectManager.getInstance().getOpenProjects();
        if (ps.length == 0) throw new IllegalStateException("no open project");
        return ps[0];
    }

    private static Window target() {
        Window best = null;
        for (Window w : Window.getWindows()) {
            if (!w.isShowing()) continue;
            if (best == null || w.getOwner() != null) best = w;   // a popup or dialog wins over its frame
        }
        JFrame frame = WindowManager.getInstance().getFrame(project());
        return best != null ? best : frame;
    }

    private static Component focus(Window w) {
        Component c = KeyboardFocusManager.getCurrentKeyboardFocusManager().getFocusOwner();
        if (c == null) c = w.getMostRecentFocusOwner();
        if (c == null) c = w;
        return c;
    }

    private static Component editorComponent() {
        com.intellij.openapi.editor.Editor e = com.intellij.openapi.fileEditor.FileEditorManager
                .getInstance(project()).getSelectedTextEditor();
        if (e != null) return e.getContentComponent();
        return WindowManager.getInstance().getFrame(project()).getRootPane();
    }

    private static <T extends Component> T find(Component root, Class<T> type, String text) {
        if (type.isInstance(root) && root.isShowing()) {
            if (text == null && !(root instanceof javax.swing.text.JTextComponent t && !t.isEditable()))
                return type.cast(root);
            if (root instanceof AbstractButton b && text.equals(b.getText())) return type.cast(root);
        }
        if (root instanceof Container c) {
            for (Component k : c.getComponents()) {
                T t = find(k, type, text);
                if (t != null) return t;
            }
        }
        return null;
    }

    private static void post(AWTEvent e) {
        Toolkit.getDefaultToolkit().getSystemEventQueue().postEvent(e);
    }

    private static String run(String path, Map<String, String> q) throws Exception {
        switch (path) {
            case "/frame": {
                JFrame f = WindowManager.getInstance().getFrame(project());
                f.setBounds(Integer.parseInt(q.get("x")), Integer.parseInt(q.get("y")),
                        Integer.parseInt(q.get("w")), Integer.parseInt(q.get("h")));
                return f.getBounds().toString();
            }
            case "/open": {
                Project p = project();
                VirtualFile vf = LocalFileSystem.getInstance()
                        .refreshAndFindFileByPath(p.getBasePath() + "/" + q.get("file"));
                if (vf == null) throw new IllegalArgumentException("no file " + q.get("file"));
                int line = Integer.parseInt(q.getOrDefault("line", "1")) - 1;
                new OpenFileDescriptor(p, vf, line, 0).navigate(true);
                return vf.getPath();
            }
            case "/action": {
                com.intellij.openapi.actionSystem.ActionManager am =
                        com.intellij.openapi.actionSystem.ActionManager.getInstance();
                com.intellij.openapi.actionSystem.AnAction a = am.getAction(q.get("id"));
                if (a == null) throw new IllegalArgumentException("no action " + q.get("id"));
                Component owner = KeyboardFocusManager.getCurrentKeyboardFocusManager().getFocusOwner();
                Component c = q.containsKey("frame")
                        ? WindowManager.getInstance().getFrame(project()).getRootPane()
                        : q.containsKey("focus") && owner != null ? owner : editorComponent();
                // Later, not now: an action that opens a modal dialog would block this call.
                ApplicationManager.getApplication().invokeLater(
                        () -> am.tryToExecute(a, null, c, "promo", true));
                return c.getClass().getName();
            }
            case "/key": {
                Window w = target();
                Component c = focus(w);
                int code = Integer.parseInt(q.get("code"));
                int mods = Integer.parseInt(q.getOrDefault("mods", "0"));
                long now = System.currentTimeMillis();
                post(new KeyEvent(c, KeyEvent.KEY_PRESSED, now, mods, code, KeyEvent.CHAR_UNDEFINED));
                post(new KeyEvent(c, KeyEvent.KEY_RELEASED, now + 1, mods, code, KeyEvent.CHAR_UNDEFINED));
                return c.getClass().getName();
            }
            case "/type": {
                Component c = focus(target());
                long now = System.currentTimeMillis();
                for (char ch : q.get("text").toCharArray()) {
                    post(new KeyEvent(c, KeyEvent.KEY_TYPED, now++, 0, KeyEvent.VK_UNDEFINED, ch));
                }
                return c.getClass().getName();
            }
            case "/click":
            case "/move": {
                Window w = target();
                Point p = new Point(Integer.parseInt(q.get("x")), Integer.parseInt(q.get("y")));
                Component c = SwingUtilities.getDeepestComponentAt(w, p.x, p.y);
                if (c == null) c = w;
                Point local = SwingUtilities.convertPoint(w, p, c);
                long now = System.currentTimeMillis();
                if (path.equals("/move")) {
                    post(new MouseEvent(c, MouseEvent.MOUSE_MOVED, now, 0, local.x, local.y, 0, false));
                    return c.getClass().getName();
                }
                int count = Integer.parseInt(q.getOrDefault("count", "1"));
                for (int i = 1; i <= count; i++) {
                    post(new MouseEvent(c, MouseEvent.MOUSE_PRESSED, now, InputEvent.BUTTON1_DOWN_MASK, local.x, local.y, i, false, MouseEvent.BUTTON1));
                    post(new MouseEvent(c, MouseEvent.MOUSE_RELEASED, now + 1, 0, local.x, local.y, i, false, MouseEvent.BUTTON1));
                    post(new MouseEvent(c, MouseEvent.MOUSE_CLICKED, now + 2, 0, local.x, local.y, i, false, MouseEvent.BUTTON1));
                }
                return c.getClass().getName();
            }
            case "/settext": {
                javax.swing.text.JTextComponent t = find(target(), javax.swing.text.JTextComponent.class, null);
                if (t == null) throw new IllegalStateException("no text field");
                t.setText(q.get("text"));
                t.setCaretPosition(t.getDocument().getLength());
                return t.getClass().getName();
            }
            case "/button": {
                for (Window w : Window.getWindows()) {
                    if (!w.isShowing()) continue;
                    AbstractButton b = find(w, AbstractButton.class, q.get("text"));
                    if (b != null) {
                        AbstractButton fb = b;
                        ApplicationManager.getApplication().invokeLater(fb::doClick,
                                com.intellij.openapi.application.ModalityState.any());
                        return b.getClass().getName();
                    }
                }
                throw new IllegalStateException("no button " + q.get("text"));
            }
            case "/findline": {
                JFrame f = WindowManager.getInstance().getFrame(project());
                String text = q.get("text");
                for (com.intellij.openapi.editor.impl.EditorComponentImpl c : com.intellij.util.ui.UIUtil
                        .findComponentsOfType(f.getRootPane(), com.intellij.openapi.editor.impl.EditorComponentImpl.class)) {
                    if (!c.isShowing()) continue;
                    com.intellij.openapi.editor.ex.EditorEx e = c.getEditor();
                    com.intellij.openapi.editor.Document doc = e.getDocument();
                    for (int i = 0; i < doc.getLineCount(); i++) {
                        String line = doc.getText(new com.intellij.openapi.util.TextRange(
                                doc.getLineStartOffset(i), doc.getLineEndOffset(i)));
                        if (!line.contains(text)) continue;
                        com.intellij.openapi.editor.LogicalPosition pos = new com.intellij.openapi.editor.LogicalPosition(i, 0);
                        e.getScrollingModel().disableAnimation();
                        e.getScrollingModel().scrollTo(pos, com.intellij.openapi.editor.ScrollType.CENTER);
                        Point xy = e.logicalPositionToXY(pos);
                        Point at = SwingUtilities.convertPoint(c, new Point(0, xy.y + e.getLineHeight() / 2), f.getRootPane());
                        JComponent g = e.getGutterComponentEx();
                        Point gx = SwingUtilities.convertPoint(g, new Point(0, 0), f.getRootPane());
                        return gx.x + " " + g.getWidth() + " " + at.y;
                    }
                }
                throw new IllegalStateException("no showing line holds " + text);
            }
            case "/closepopups": {
                return String.valueOf(com.intellij.ide.IdeEventQueue.getInstance().getPopupManager().closeAllPopups());
            }
            case "/focus": {
                // set=1: give the project frame the focus back (with no window manager,
                // nothing does when a dialog closes).
                JFrame f = WindowManager.getInstance().getFrame(project());
                if ("1".equals(q.get("set"))) {
                    f.toFront();
                    // The selected tab's own focus target: a diff tab's is its viewer.
                    com.intellij.openapi.fileEditor.FileEditor fe = com.intellij.openapi.fileEditor.FileEditorManager
                            .getInstance(project()).getSelectedEditor();
                    Component c = fe != null && fe.getPreferredFocusedComponent() != null
                            ? fe.getPreferredFocusedComponent() : editorComponent();
                    com.intellij.openapi.wm.IdeFocusManager.getGlobalInstance().requestFocus(c, true);
                }
                KeyboardFocusManager k = KeyboardFocusManager.getCurrentKeyboardFocusManager();
                return "active=" + (k.getActiveWindow() == null ? null : k.getActiveWindow().getClass().getSimpleName())
                        + " owner=" + (k.getFocusOwner() == null ? null : k.getFocusOwner().getClass().getSimpleName());
            }
            case "/data": {
                // What an action run with focus=1 would see: the focus owner and its file.
                Component owner = KeyboardFocusManager.getCurrentKeyboardFocusManager().getFocusOwner();
                if (owner == null) return "owner=null";
                com.intellij.openapi.actionSystem.DataContext dc =
                        com.intellij.ide.DataManager.getInstance().getDataContext(owner);
                Object vf = dc.getData(com.intellij.openapi.actionSystem.CommonDataKeys.VIRTUAL_FILE);
                Object ed = dc.getData(com.intellij.openapi.actionSystem.CommonDataKeys.EDITOR);
                return "owner=" + owner.getClass().getSimpleName() + " file=" + vf + " editor=" + (ed == null ? null : ed.getClass().getSimpleName());
            }
            case "/smart": {
                return com.intellij.openapi.project.DumbService.getInstance(project()).isDumb() ? "dumb" : "smart";
            }
            case "/keymap": {
                com.intellij.openapi.keymap.ex.KeymapManagerEx m = com.intellij.openapi.keymap.ex.KeymapManagerEx.getInstanceEx();
                com.intellij.openapi.keymap.Keymap km = m.getKeymap(q.get("name"));
                if (km == null) {
                    StringBuilder all = new StringBuilder();
                    for (com.intellij.openapi.keymap.Keymap k : m.getAllKeymaps()) all.append(k.getName()).append("; ");
                    throw new IllegalArgumentException("no keymap " + q.get("name") + "; there are " + all);
                }
                m.setActiveKeymap(km);
                return km.getName();
            }
            case "/shortcut": {
                com.intellij.openapi.keymap.Keymap km =
                        com.intellij.openapi.keymap.KeymapManager.getInstance().getActiveKeymap();
                StringBuilder sb = new StringBuilder(km.getName());
                for (com.intellij.openapi.actionSystem.Shortcut s : km.getShortcuts(q.get("id"))) {
                    sb.append(' ').append(s);
                }
                return sb.toString();
            }
            case "/windows": {
                StringBuilder sb = new StringBuilder();
                for (Window w : Window.getWindows()) {
                    if (w.isShowing()) sb.append(w.getClass().getName()).append(' ').append(w.getBounds()).append('\n');
                }
                return sb.toString();
            }
            default:
                throw new IllegalArgumentException("unknown " + path);
        }
    }
}
