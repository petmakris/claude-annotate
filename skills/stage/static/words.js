// The stage's own words, in the two languages of the call page: English and Greek. The call page tells the stage which
// one it is in (`stage:lang`); a stage opened alone follows the browser's language. A board's own content (a table, a
// diagram's labels) is never touched here: only the words the stage itself adds around it.
//
//   w("key", {name: value})   the words for `key` in the language now; {name} is filled in. A key with a count has
//                             .one and .other forms: wn("steps", 3) is "3 steps".
//
// Every key has an English and a Greek form (test_stage_words.py checks it, and that every key the stage's code
// uses is in the table).
export const WORDS = {
  en: {
    "back.voice": "Back to the voice",
    "board.prev": "Previous board", "board.next": "Next board", "board.all": "All boards", "boards": "Boards", "stage.label": "Stage",
    "board.pos": "Board {i} of {n}", "board.count": "{n} boards", "board.all.aria": "{pos}, all boards", "board.changed": ", one changed",
    "stop.group": "The answer asks",
    "empty.title": "The stage is empty", "empty.line": "When Claude shows code, a diagram, a table or a page, it appears here.",
    "kind.code": "Code", "kind.diagram": "Diagram", "kind.table": "Table", "kind.page": "Page",
    "fail.title": "The stage did not load", "fail.line": "Could not load the stage: {why}.", "retry": "Try again",
    "step.prev": "Previous step", "step.next": "Next step", "step.all": "All shown", "step.all.again": "All shown. Start the steps again",
    "step.of": "Step {n} of {total}", "steps.one": "{n} step", "steps.other": "{n} steps", "step.then.next": "{label}. Next step",
    "copy": "Copy", "copied": "Copied", "copy.failed": "Copy failed", "wrap": "Wrap lines", "open": "Open ↗", "close": "Close",
    "ask.about": "Ask about this", "play.here": "Play from here", "play.none": "No answer says this step",
    "points.title": "Key points", "points.cap": "Answer {n}", "points.earlier": "Earlier",
    "points.count.one": "{n} key point", "points.count.other": "{n} key points", "updated.aria": "{title}, updated",
    "say.hint": "Answer in the text field, or press Talk.",
    "from.answer": " · from answer {n}", "repairs.one": " · {n} repair", "repairs.other": " · {n} repairs",
    "ago.now": "Updated just now", "ago.min": "Updated {n} min ago", "ago.hour.one": "Updated {n} hour ago", "ago.hour.other": "Updated {n} hours ago",
    "ago.day": "Updated {n} d ago",
    "meta.table.one": "Table · {n} row", "meta.table.other": "Table · {n} rows",
    "meta.points.one": "{n} key point from this call", "meta.points.other": "{n} key points from this call",
    "meta.parts.one": "{n} part", "meta.parts.other": "{n} parts",
    "note.highlight": "Highlighting did not load, so this is plain text.", "note.map": "The map could not be made safe to show, so it is not shown.",
    "note.scene": "The scene could not be made safe to show, so it is not shown.", "note.table": "The table formatter did not load, so this is the plain text.",
    "note.mermaid": "The stage no longer draws Mermaid, so this is the diagram's source.",
    "file.wait": "Waiting for {path}", "file.fail": "{path} could not be read ({why}).",
    // a table that scrolls
    "rows.more.one": "{n} more row", "rows.more.other": "{n} more rows", "row.n": "row {n}", "not.said": "Not said in the voice.",
    // the lanes
    "gap.none": "No step here", "who.key": "Who is who", "follow.actor": "Follow {name}",
    "phase.fold": "Fold this phase", "phase.open": "Open this phase", "phase.steps": "steps {a}–{b}",
    "group.fold": "Fold this {kind}", "group.open": "Open this {kind}", "group.folded": "{steps} folded · open",
    "lanes.fail": "This diagram could not be drawn.",
    "seq.call": "Step {n}: {from} to {to}, {label}", "seq.self": "Step {n}: {from} to itself, {label}",
    "seq.reply": "Step {n}: {from} replies to {to}, {label}", "seq.band": "Step {n}: stretch, {label}",
    "kind.reply": "reply", "kind.own": "own call", "kind.stretch": "stretch", "kind.call": "call",
    "pop.itself": "to itself", "pop.answers": "Answers", "pop.answered": "Answered by", "pop.note": "Note", "pop.only": "only when {cond}",
    "pop.link": "step {n}: {label}",
    "cmp.which": "Which flow", "cmp.before": "Before", "cmp.after": "After",
    "mark.same": "the same", "mark.changed": "changed", "mark.added": "new", "mark.removed": "removed", "mark.moved": "moved",
    // the reading lists of the drawn boards (map, graph, bars): what a screen reader says of a drawing
    "read.arrows": "Arrows", "read.values": "Values",
    "read.edge": "{from} goes to {to}", "read.edge.label": "{from}, {label}, goes to {to}", "read.dashed": ", dashed",
    "read.link": "{from} is joined to {to}", "read.link.label": "{from}, {label}, is joined to {to}",
    "read.state.new": "{label} is new", "read.state.ghost": "{label} stays, no longer reached", "read.state.struck": "{label} is removed",
    "read.bar": "{label}: {value}", "read.bar.note": "{label}: {value}, {note}", "read.threshold": "{label}, the line: {value}",
  },
  el: {
    "back.voice": "Πίσω στη φωνή",
    "board.prev": "Προηγούμενος πίνακας", "board.next": "Επόμενος πίνακας", "board.all": "Όλοι οι πίνακες", "boards": "Πίνακες", "stage.label": "Σκηνή",
    "board.pos": "Πίνακας {i} από {n}", "board.count": "{n} πίνακες", "board.all.aria": "{pos}, όλοι οι πίνακες", "board.changed": ", ένας άλλαξε",
    "stop.group": "Η απάντηση ρωτά",
    "empty.title": "Η σκηνή είναι άδεια", "empty.line": "Όταν ο Claude δείξει κώδικα, διάγραμμα, πίνακα ή σελίδα, εμφανίζεται εδώ.",
    "kind.code": "Κώδικας", "kind.diagram": "Διάγραμμα", "kind.table": "Πίνακας", "kind.page": "Σελίδα",
    "fail.title": "Η σκηνή δεν φορτώθηκε", "fail.line": "Δεν φορτώθηκε η σκηνή: {why}.", "retry": "Δοκιμάστε ξανά",
    "step.prev": "Προηγούμενο βήμα", "step.next": "Επόμενο βήμα", "step.all": "Όλα εμφανίστηκαν", "step.all.again": "Όλα εμφανίστηκαν. Ξεκινήστε ξανά τα βήματα",
    "step.of": "Βήμα {n} από {total}", "steps.one": "{n} βήμα", "steps.other": "{n} βήματα", "step.then.next": "{label}. Επόμενο βήμα",
    "copy": "Αντιγραφή", "copied": "Αντιγράφηκε", "copy.failed": "Η αντιγραφή απέτυχε", "wrap": "Αναδίπλωση γραμμών", "open": "Άνοιγμα ↗", "close": "Κλείσιμο",
    "ask.about": "Ρωτήστε γι' αυτό", "play.here": "Αναπαραγωγή από εδώ", "play.none": "Καμία απάντηση δεν λέει αυτό το βήμα",
    "points.title": "Βασικά σημεία", "points.cap": "Απάντηση {n}", "points.earlier": "Νωρίτερα",
    "points.count.one": "{n} βασικό σημείο", "points.count.other": "{n} βασικά σημεία", "updated.aria": "{title}, ενημερώθηκε",
    "say.hint": "Απαντήστε στο πεδίο κειμένου ή πατήστε Ομιλία.",
    "from.answer": " · από την απάντηση {n}", "repairs.one": " · {n} διόρθωση", "repairs.other": " · {n} διορθώσεις",
    "ago.now": "Ενημερώθηκε μόλις τώρα", "ago.min": "Ενημερώθηκε πριν από {n} λεπτά", "ago.hour.one": "Ενημερώθηκε πριν από {n} ώρα", "ago.hour.other": "Ενημερώθηκε πριν από {n} ώρες",
    "ago.day": "Ενημερώθηκε πριν από {n} ημ.",
    "meta.table.one": "Πίνακας · {n} γραμμή", "meta.table.other": "Πίνακας · {n} γραμμές",
    "meta.points.one": "{n} βασικό σημείο από αυτή την κλήση", "meta.points.other": "{n} βασικά σημεία από αυτή την κλήση",
    "meta.parts.one": "{n} μέρος", "meta.parts.other": "{n} μέρη",
    "note.highlight": "Η επισήμανση δεν φορτώθηκε, γι' αυτό το κείμενο είναι απλό.", "note.map": "Ο χάρτης δεν έγινε ασφαλής για εμφάνιση, γι' αυτό δεν εμφανίζεται.",
    "note.scene": "Η σκηνή δεν έγινε ασφαλής για εμφάνιση, γι' αυτό δεν εμφανίζεται.", "note.table": "Ο μορφοποιητής πίνακα δεν φορτώθηκε, γι' αυτό είναι το απλό κείμενο.",
    "note.mermaid": "Η σκηνή δεν σχεδιάζει πια Mermaid, γι' αυτό εδώ είναι ο πηγαίος κώδικας του διαγράμματος.",
    "file.wait": "Αναμονή για το {path}", "file.fail": "Δεν ήταν δυνατή η ανάγνωση του {path} ({why}).",
    "rows.more.one": "Ακόμη {n} γραμμή", "rows.more.other": "Ακόμη {n} γραμμές", "row.n": "γραμμή {n}", "not.said": "Δεν λέγεται στη φωνή.",
    "gap.none": "Δεν υπάρχει βήμα εδώ", "who.key": "Ποιος είναι ποιος", "follow.actor": "Παρακολούθηση: {name}",
    "phase.fold": "Σύμπτυξη αυτής της φάσης", "phase.open": "Άνοιγμα αυτής της φάσης", "phase.steps": "βήματα {a}–{b}",
    "group.fold": "Σύμπτυξη: {kind}", "group.open": "Άνοιγμα: {kind}", "group.folded": "{steps} συμπτυγμένα · άνοιγμα",
    "lanes.fail": "Δεν ήταν δυνατό να σχεδιαστεί αυτό το διάγραμμα.",
    "seq.call": "Βήμα {n}: {from} προς {to}, {label}", "seq.self": "Βήμα {n}: {from} προς τον εαυτό του, {label}",
    "seq.reply": "Βήμα {n}: {from} απαντά προς {to}, {label}", "seq.band": "Βήμα {n}: ενότητα, {label}",
    "kind.reply": "απάντηση", "kind.own": "δική του κλήση", "kind.stretch": "ενότητα", "kind.call": "κλήση",
    "pop.itself": "προς τον εαυτό του", "pop.answers": "Απαντά σε", "pop.answered": "Απαντήθηκε από", "pop.note": "Σημείωση", "pop.only": "μόνο όταν {cond}",
    "pop.link": "βήμα {n}: {label}",
    "cmp.which": "Ποια ροή", "cmp.before": "Πριν", "cmp.after": "Μετά",
    "mark.same": "ίδιο", "mark.changed": "άλλαξε", "mark.added": "νέο", "mark.removed": "αφαιρέθηκε", "mark.moved": "μετακινήθηκε",
    "read.arrows": "Βέλη", "read.values": "Τιμές",
    "read.edge": "{from} πηγαίνει προς {to}", "read.edge.label": "{from}, {label}, πηγαίνει προς {to}", "read.dashed": ", διακεκομμένο",
    "read.link": "{from} συνδέεται με {to}", "read.link.label": "{from}, {label}, συνδέεται με {to}",
    "read.state.new": "{label}: νέο", "read.state.ghost": "{label}: μένει, αλλά δεν το φτάνει πια τίποτα", "read.state.struck": "{label}: αφαιρέθηκε",
    "read.bar": "{label}: {value}", "read.bar.note": "{label}: {value}, {note}", "read.threshold": "{label}, η γραμμή: {value}",
  },
};

const fromBrowser = () => (typeof navigator !== "undefined" && /^el\b/i.test(navigator.language || "") ? "el" : "en");
let lang = fromBrowser();
export const getLang = () => lang;
// Returns whether the language changed.
export function setLang(next) {
  next = next === "el" ? "el" : next === "en" ? "en" : fromBrowser();
  if (next === lang) return false;
  lang = next;
  return true;
}
export function w(key, vars) {
  const s = WORDS[lang][key] ?? WORDS.en[key] ?? key;
  return vars ? s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? "")) : s;
}
// A count: the key's .one for 1, else .other; {n} is the count.
export const wn = (key, n, vars) => w(key + (n === 1 ? ".one" : ".other"), { n, ...(vars || {}) });
