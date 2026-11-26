// The page's own words, in English and in Greek (I). One small table per language and t(key, vars): the words of the page are looked
// up here, never written where they are shown. The language is the user's "Speech language" choice in the settings: English or
// Greek as chosen, and with Detect the language of the latest answer (the browser's language until there is one). The choice sets
// <html lang>, and applyLang() puts the words into the markup that carries data-t (text), data-t-aria (aria-label), data-t-tip
// (the tooltip), data-t-title and data-t-ph (placeholder). What the server and the answers say is not here: it is the answer's own
// language. A key missing from Greek falls back to English (test_call_i18n.py holds the two tables to the same keys).
// Placeholders are {name}; a count has a key with .one and .other (tn).
const I18N = {
  en: {
    // the page
    "skip.links": "Skip links", "skip.message": "Skip to the message", "skip.player": "Skip to the player", "skip.latest": "Jump to the latest answer",
    "stage.title": "Stage", "stage.loading": "Loading the stage…", "stage.failed": "The stage did not load.", "stage.reload": "Reload stage",
    "stage.open": "Open in a new tab", "stage.none": "The stage is not available for this call.",
    "panel.name": "The call", "panel.resize": "Resize the panel", "panel.drag": "Drag to resize", "panel.collapse": "Collapse the panel",
    "panel.collapse.tip": "Collapse", "panel.expand": "Expand the panel", "panel.expand.tip": "Expand",
    "head.search": "Search the conversation", "head.search.tip": "Search", "head.calls": "Calls", "head.fullscreen": "Full screen",
    "head.fullscreen.leave": "Leave full screen", "head.settings": "Settings", "dismiss": "Dismiss", "close": "Close", "retry": "Retry",
    "strip.resume": "Resume here", "strip.autoplay.aria": "Play new answers by themselves", "strip.autoplay.note": "New answers will not play by themselves",
    "strip.autoplay.on": "Autoplay on", "strip.autoplay.off": "Autoplay off",
    "strip.autoplay.on.tip": "Autoplay is on: new answers play by themselves", "strip.autoplay.off.tip": "Autoplay is off: new answers wait for Play",
    "tv.offer": "Reading from across the room?", "tv.use": "Use TV size", "tv.notnow": "Not now",
    "welcome.name": "Welcome back", "welcome.play": "Play the new", "welcome.read": "Read them",
    "player.back": "Previous sentence", "player.back.tip": "Previous sentence · ←", "player.play": "Play", "player.next": "Next sentence",
    "player.next.tip": "Next sentence · →", "player.seek": "Position in the answer", "player.speed.tip": "Voice speed · Alt+S",
    "list.conversation": "Conversation", "wait.name": "Your question is being answered", "list.earlier": "Earlier answers", "list.search": "Search answers", "list.empty": "Nothing has been said yet.",
    "foot.jump": "Back to the voice", "foot.undo": "Undo", "foot.stop": "The answer asks", "foot.mode": "How you talk", "foot.compose": "Talk or type",
    "foot.cancel": "Cancel", "foot.cancel.tip": "Cancel", "foot.type": "Type a message", "foot.send": "Send text", "foot.send.tip": "Send",
    "foot.done": "Done", "foot.talk": "Talk",
    "hint.play": "play or pause", "hint.sentence": "sentence", "hint.keys": "All keys", "hint.keys.aria": "Keyboard shortcuts",
    "rail.back": "Back one sentence",
    // settings
    "set.screen": "Screen", "set.desk": "Desk", "set.tv": "TV", "set.panel": "Panel", "set.panel.where": "Where the panel sits", "set.left": "Left",
    "set.right": "Right", "set.theme": "Theme", "set.light": "Light", "set.dark": "Dark", "set.system": "System", "set.voice": "Voice",
    "set.lang": "Speech language", "set.lang.aria": "Language I speak", "set.speed": "Voice speed", "set.autoplay": "Play new answers by themselves",
    "set.follow": "Stage follows the voice", "set.keys": "Keyboard shortcuts", "set.demo": "Stage demo", "set.demo.sub": "Every board, explained, in a new tab",
    "set.end": "End call", "set.close": "Close", "lang.auto": "Detect",
    "voice.cloud": "a cloud voice: quick to start, billed per character", "voice.local": "A voice made on this computer: free, a little slower to start",
    "voice.failed": "The voice was not changed.", "voice.hear": "Hear {name}", "voice.sample": "The sample did not play.",
    "fs.failed": "Full screen failed: {why}", "demo.failed": "The stage demo did not open: {why}", "http": "HTTP {code}",
    "speed.aria": "Voice speed {x}×. Press for the next speed.", "speed.say": "Voice speed {x}×",
    // keys
    "keys.title": "Keyboard shortcuts", "keys.close": "Close the shortcuts",
    "keys.note": "Every key has a button. Letters go to the message field, so the shortcuts use Alt.",
    "g.listen": "Listening", "g.move": "Moving around", "g.talk": "Talking",
    "k.play": "Play or pause the answer", "k.sentence": "Back or forward one sentence", "k.speed": "Next voice speed",
    "k.message": "Go to the message field", "k.player": "Go to the player", "k.voice": "Follow the voice again", "k.keys": "Show this list",
    "k.close": "Close the open window", "k.send": "Send the message", "k.newline": "New line in the message", "k.talk": "Talk, or Done while recording",
    // talking
    "mode.type": "Type", "mode.talk": "Talk", "mode.live": "Live", "mode.locked": "Finish the recording first",
    "mic.listen": "Listen", "mic.start": "Start listening", "mic.here": "Listen here", "mic.unmute": "Unmute", "mic.mute": "Mute",
    "mic.unavailable": "This page cannot reach a microphone. Open it over https or on localhost.", "mic.none": "No microphone: {why}",
    "mic.lost": "The microphone was lost. Press the mic to listen again.", "mic.asleep": "Asleep after 10 minutes of quiet. Press the mic to listen.",
    "send.http": "Sending failed: HTTP {code}", "send.failed": "Sending failed: {why}", "send.restarting": "the talk server is restarting",
    "send.reconnect": "Reconnecting… your recording is kept and will be written out.",
    "heard.how": " in {s} s of recording",
    "heard.dead": "Nothing was heard{how}: the microphone gave almost no signal. Check that it is switched on and not muted, then try again.",
    "heard.faint": "Nothing was heard{how}, though the microphone picked up some sound. Try again a little closer to it.",
    "barge.talk": "talking", "barge.keyword": "“wait”",
    "barge.pill": "Interrupt: {how}", "barge.aria": "Interrupt Claude by {how}. Press to change.",
    "barge.talk.title": "Interrupt: starting to talk stops Claude's answer. Press to stop it only when you say “wait”.",
    "barge.keyword.title": "Interrupt: Claude's answer stops only when you say “wait”. Press to stop it as soon as you start talking.",
    "pause.pill": "Send after {s} s", "pause.aria": "Send after a pause of {s} seconds. Press to change.",
    "pause.title": "Send after: how long you stay quiet before your turn is sent, now {now} s. Press for {next} s.",
    "turn.rec": "Recording", "turn.work": "Writing it out", "turn.off": "Live is off", "turn.suspended": "Click to start listening",
    "turn.parked": "Live on another screen", "turn.muted": "Muted", "turn.nosound": "No sound heard", "turn.hearing": "Hearing you",
    "turn.typing": "Typing", "turn.claude.working": "Claude is working", "turn.claude.speaking": "Claude is speaking", "turn.listening": "Listening",
    "turn.yours": "Your turn",
    "ph.wait": "Add to your question", "ph.type": "Type a message", "ph.live": "Just speak, or type here", "ph.talk": "Type, or press the mic",
    "live.nocatch": "Didn't catch that.", "live.slowest": "Already as slow as it goes.", "live.fastest": "Already as fast as it goes.",
    "live.slower": "Slower: {x}×", "live.faster": "Faster: {x}×", "live.stopped": "Stopped listening. Press the mic to listen.", "live.taken": "Taken back.",
    // the call's state
    "s.listening": "Listening to you", "s.transcribing": "Turning your words into text", "s.stalled": "Claude has not picked this up yet",
    "s.sent": "Sent, waiting for Claude to pick it up", "s.answering": "Claude is answering", "s.next": "Answer {n} is next",
    "s.elsewhere": "Playing on another screen", "s.playing": "Playing answer {n}", "s.following": " · following the board", "s.pinned": " · board pinned",
    "s.paused": "Paused at answer {n}", "s.closed": "Call closed", "s.ended": "The call has ended",
    "s.waiting": "Waiting for you", "s.first": "Waiting for your first question",
    "answers.unheard.one": "{n} answer not heard", "answers.unheard.other": "{n} answers not heard",
    "boards.one": "{n} board", "boards.other": "{n} boards",
    "others.one": "1 other call needs you", "others.other": "{n} other calls need you", "others.list": "Calls that need you: {list}",
    "floor.words": "Paused: {who} took the voice.", "floor.another": "another call",
    "away.text": "away {t}", "away.audio": "{t} of audio", "away.working": "Claude is still working", "away.on": " on “{q}”",
    "away.making": "Voice being made", "away.play.one": "Play the new answer", "away.play.other": "Play the {n} new",
    "since.left": "Since you left", "since.count": "{n} not heard", "since.play": "Play these", "t.min": "{n} min", "t.h": "{n} h", "t.d": "{n} d", "t.s": "{n} s",
    "ann.arrived": "Answer {n} arrived", "ann.ended": "The call has ended.", "ann.board": "Board: {text}.",
    // the calls
    "c.new.one": "New answer", "c.new.other": "{n} new answers", "c.ended": "Ended", "c.stalled": "Stalled", "c.answering": "Answering",
    "c.talking": "Talking now", "c.waiting": "Waiting for you", "c.listening": "Listening", "c.playing": "Playing",
    "c.here": "Here · {word}", "c.thiscall": "this call · ", "c.all": "All calls", "c.open": "Open “{topic}”", "c.next": "Next waiting",
    "c.label": "Calls: {text}. {words}", "c.newin": "New answer in “{topic}”.", "c.in": "{word} in “{topic}”",
    "age.now": "now", "age.m": "{n}m", "age.h": "{n}h", "age.d": "{n}d", "tab.new": "New",
  },
  el: {
    "skip.links": "Σύνδεσμοι παράλειψης", "skip.message": "Μετάβαση στο μήνυμα", "skip.player": "Μετάβαση στη συσκευή αναπαραγωγής",
    "skip.latest": "Μετάβαση στην τελευταία απάντηση",
    "stage.title": "Σκηνή", "stage.loading": "Φόρτωση της σκηνής…", "stage.failed": "Η σκηνή δεν φορτώθηκε.", "stage.reload": "Επαναφόρτωση σκηνής",
    "stage.open": "Άνοιγμα σε νέα καρτέλα", "stage.none": "Η σκηνή δεν είναι διαθέσιμη για αυτή την κλήση.",
    "panel.name": "Η κλήση", "panel.resize": "Αλλαγή μεγέθους του πάνελ", "panel.drag": "Σύρετε για αλλαγή μεγέθους", "panel.collapse": "Σύμπτυξη του πάνελ",
    "panel.collapse.tip": "Σύμπτυξη", "panel.expand": "Ανάπτυξη του πάνελ", "panel.expand.tip": "Ανάπτυξη",
    "head.search": "Αναζήτηση στη συνομιλία", "head.search.tip": "Αναζήτηση", "head.calls": "Κλήσεις", "head.fullscreen": "Πλήρης οθόνη",
    "head.fullscreen.leave": "Έξοδος από πλήρη οθόνη", "head.settings": "Ρυθμίσεις", "dismiss": "Απόρριψη", "close": "Κλείσιμο", "retry": "Επανάληψη",
    "strip.resume": "Συνέχεια εδώ", "strip.autoplay.aria": "Αυτόματη αναπαραγωγή των νέων απαντήσεων",
    "strip.autoplay.note": "Οι νέες απαντήσεις δεν θα παίζουν μόνες τους",
    "strip.autoplay.on": "Αυτόματη αναπαραγωγή: ναι", "strip.autoplay.off": "Αυτόματη αναπαραγωγή: όχι",
    "strip.autoplay.on.tip": "Η αυτόματη αναπαραγωγή είναι ενεργή: οι νέες απαντήσεις παίζουν μόνες τους",
    "strip.autoplay.off.tip": "Η αυτόματη αναπαραγωγή είναι κλειστή: οι νέες απαντήσεις περιμένουν το Αναπαραγωγή",
    "tv.offer": "Διαβάζετε από μακριά;", "tv.use": "Μέγεθος τηλεόρασης", "tv.notnow": "Όχι τώρα",
    "welcome.name": "Καλώς ήρθατε ξανά", "welcome.play": "Αναπαραγωγή των νέων", "welcome.read": "Διάβασμα",
    "player.back": "Προηγούμενη πρόταση", "player.back.tip": "Προηγούμενη πρόταση · ←", "player.play": "Αναπαραγωγή", "player.next": "Επόμενη πρόταση",
    "player.next.tip": "Επόμενη πρόταση · →", "player.seek": "Θέση στην απάντηση", "player.speed.tip": "Ταχύτητα φωνής · Alt+S",
    "list.conversation": "Συνομιλία", "wait.name": "Η ερώτησή σας απαντάται", "list.earlier": "Προηγούμενες απαντήσεις", "list.search": "Αναζήτηση απαντήσεων", "list.empty": "Δεν έχει ειπωθεί τίποτα ακόμα.",
    "foot.jump": "Πίσω στη φωνή", "foot.undo": "Αναίρεση", "foot.stop": "Η απάντηση ρωτά", "foot.mode": "Πώς μιλάτε", "foot.compose": "Μιλήστε ή πληκτρολογήστε",
    "foot.cancel": "Ακύρωση", "foot.cancel.tip": "Ακύρωση", "foot.type": "Πληκτρολογήστε ένα μήνυμα", "foot.send": "Αποστολή κειμένου", "foot.send.tip": "Αποστολή",
    "foot.done": "Τέλος", "foot.talk": "Μιλήστε",
    "hint.play": "αναπαραγωγή ή παύση", "hint.sentence": "πρόταση", "hint.keys": "Όλα τα πλήκτρα", "hint.keys.aria": "Συντομεύσεις πληκτρολογίου",
    "rail.back": "Πίσω μία πρόταση",
    "set.screen": "Οθόνη", "set.desk": "Γραφείο", "set.tv": "Τηλεόραση", "set.panel": "Πάνελ", "set.panel.where": "Πού βρίσκεται το πάνελ", "set.left": "Αριστερά",
    "set.right": "Δεξιά", "set.theme": "Θέμα", "set.light": "Φωτεινό", "set.dark": "Σκούρο", "set.system": "Σύστημα", "set.voice": "Φωνή",
    "set.lang": "Γλώσσα ομιλίας", "set.lang.aria": "Η γλώσσα που μιλάω", "set.speed": "Ταχύτητα φωνής", "set.autoplay": "Αυτόματη αναπαραγωγή των νέων απαντήσεων",
    "set.follow": "Η σκηνή ακολουθεί τη φωνή", "set.keys": "Συντομεύσεις πληκτρολογίου", "set.demo": "Επίδειξη της σκηνής", "set.demo.sub": "Κάθε πίνακας, με εξήγηση, σε νέα καρτέλα",
    "set.end": "Τέλος κλήσης", "set.close": "Κλείσιμο", "lang.auto": "Ανίχνευση",
    "voice.cloud": "μια φωνή στο cloud: ξεκινά γρήγορα, χρεώνεται ανά χαρακτήρα", "voice.local": "Μια φωνή που παράγεται σε αυτόν τον υπολογιστή: δωρεάν, ξεκινά λίγο πιο αργά",
    "voice.failed": "Η φωνή δεν άλλαξε.", "voice.hear": "Ακούστε τη φωνή {name}", "voice.sample": "Το δείγμα δεν αναπαράχθηκε.",
    "fs.failed": "Η πλήρης οθόνη απέτυχε: {why}", "demo.failed": "Η επίδειξη της σκηνής δεν άνοιξε: {why}", "http": "HTTP {code}",
    "speed.aria": "Ταχύτητα φωνής {x}×. Πατήστε για την επόμενη ταχύτητα.", "speed.say": "Ταχύτητα φωνής {x}×",
    "keys.title": "Συντομεύσεις πληκτρολογίου", "keys.close": "Κλείσιμο των συντομεύσεων",
    "keys.note": "Κάθε πλήκτρο έχει κουμπί. Τα γράμματα πηγαίνουν στο πεδίο μηνύματος, γι' αυτό οι συντομεύσεις χρησιμοποιούν το Alt.",
    "g.listen": "Ακρόαση", "g.move": "Μετακίνηση", "g.talk": "Ομιλία",
    "k.play": "Αναπαραγωγή ή παύση της απάντησης", "k.sentence": "Μία πρόταση πίσω ή μπροστά", "k.speed": "Επόμενη ταχύτητα φωνής",
    "k.message": "Μετάβαση στο πεδίο μηνύματος", "k.player": "Μετάβαση στη συσκευή αναπαραγωγής", "k.voice": "Ακολούθηση της φωνής ξανά", "k.keys": "Εμφάνιση αυτής της λίστας",
    "k.close": "Κλείσιμο του ανοιχτού παραθύρου", "k.send": "Αποστολή του μηνύματος", "k.newline": "Νέα γραμμή στο μήνυμα", "k.talk": "Ομιλία ή Τέλος κατά την εγγραφή",
    "mode.type": "Πληκτρολόγηση", "mode.talk": "Ομιλία", "mode.live": "Ζωντανά", "mode.locked": "Ολοκληρώστε πρώτα την εγγραφή",
    "mic.listen": "Ακρόαση", "mic.start": "Έναρξη ακρόασης", "mic.here": "Ακρόαση εδώ", "mic.unmute": "Άρση σίγασης", "mic.mute": "Σίγαση",
    "mic.unavailable": "Αυτή η σελίδα δεν έχει πρόσβαση σε μικρόφωνο. Ανοίξτε την μέσω https ή στο localhost.", "mic.none": "Κανένα μικρόφωνο: {why}",
    "mic.lost": "Το μικρόφωνο χάθηκε. Πατήστε το μικρόφωνο για να ακούσω ξανά.", "mic.asleep": "Σε αναμονή μετά από 10 λεπτά ησυχίας. Πατήστε το μικρόφωνο για ακρόαση.",
    "send.http": "Η αποστολή απέτυχε: HTTP {code}", "send.failed": "Η αποστολή απέτυχε: {why}", "send.restarting": "ο διακομιστής της κλήσης επανεκκινεί",
    "send.reconnect": "Επανασύνδεση… η ηχογράφησή σας φυλάσσεται και θα γραφτεί.",
    "heard.how": " σε {s} δ ηχογράφησης",
    "heard.dead": "Δεν ακούστηκε τίποτα{how}: το μικρόφωνο δεν έδωσε σχεδόν καθόλου σήμα. Ελέγξτε ότι είναι ανοιχτό και δεν είναι σε σίγαση και δοκιμάστε ξανά.",
    "heard.faint": "Δεν ακούστηκε τίποτα{how}, αν και το μικρόφωνο έπιασε κάποιον ήχο. Δοκιμάστε ξανά λίγο πιο κοντά του.",
    "barge.talk": "ομιλία", "barge.keyword": "«περίμενε»",
    "barge.pill": "Διακοπή: {how}", "barge.aria": "Διακοπή του Claude με {how}. Πατήστε για αλλαγή.",
    "barge.talk.title": "Διακοπή: μόλις αρχίσετε να μιλάτε, η απάντηση του Claude σταματά. Πατήστε για να σταματά μόνο όταν πείτε «περίμενε».",
    "barge.keyword.title": "Διακοπή: η απάντηση του Claude σταματά μόνο όταν πείτε «περίμενε». Πατήστε για να σταματά μόλις αρχίσετε να μιλάτε.",
    "pause.pill": "Αποστολή μετά από {s} δ", "pause.aria": "Αποστολή μετά από παύση {s} δευτερολέπτων. Πατήστε για αλλαγή.",
    "pause.title": "Αποστολή μετά: πόση ώρα σιωπάτε πριν σταλεί η σειρά σας, τώρα {now} δ. Πατήστε για {next} δ.",
    "turn.rec": "Ηχογράφηση", "turn.work": "Μετατροπή σε κείμενο", "turn.off": "Η ζωντανή λειτουργία είναι κλειστή", "turn.suspended": "Πατήστε για έναρξη ακρόασης",
    "turn.parked": "Ζωντανά σε άλλη οθόνη", "turn.muted": "Σε σίγαση", "turn.nosound": "Δεν ακούστηκε ήχος", "turn.hearing": "Σας ακούω",
    "turn.typing": "Πληκτρολόγηση", "turn.claude.working": "Ο Claude εργάζεται", "turn.claude.speaking": "Ο Claude μιλά", "turn.listening": "Ακούω",
    "turn.yours": "Η σειρά σας",
    "ph.wait": "Προσθέστε στην ερώτησή σας", "ph.type": "Πληκτρολογήστε ένα μήνυμα", "ph.live": "Απλώς μιλήστε ή πληκτρολογήστε εδώ", "ph.talk": "Πληκτρολογήστε ή πατήστε το μικρόφωνο",
    "live.nocatch": "Δεν κατάλαβα.", "live.slowest": "Δεν γίνεται πιο αργά.", "live.fastest": "Δεν γίνεται πιο γρήγορα.",
    "live.slower": "Πιο αργά: {x}×", "live.faster": "Πιο γρήγορα: {x}×", "live.stopped": "Η ακρόαση σταμάτησε. Πατήστε το μικρόφωνο για ακρόαση.", "live.taken": "Ανακλήθηκε.",
    "s.listening": "Σας ακούω", "s.transcribing": "Μετατροπή των λόγων σας σε κείμενο", "s.stalled": "Ο Claude δεν το έχει παραλάβει ακόμα",
    "s.sent": "Στάλθηκε, αναμένεται να το παραλάβει ο Claude", "s.answering": "Ο Claude απαντά", "s.next": "Η απάντηση {n} είναι η επόμενη",
    "s.elsewhere": "Παίζει σε άλλη οθόνη", "s.playing": "Αναπαραγωγή της απάντησης {n}", "s.following": " · ακολουθεί τον πίνακα", "s.pinned": " · ο πίνακας είναι καρφιτσωμένος",
    "s.paused": "Παύση στην απάντηση {n}", "s.closed": "Η κλήση έκλεισε", "s.ended": "Η κλήση τελείωσε",
    "s.waiting": "Σας περιμένει", "s.first": "Περιμένω την πρώτη σας ερώτηση",
    "answers.unheard.one": "{n} απάντηση δεν ακούστηκε", "answers.unheard.other": "{n} απαντήσεις δεν ακούστηκαν",
    "boards.one": "{n} πίνακας", "boards.other": "{n} πίνακες",
    "others.one": "1 άλλη κλήση σας χρειάζεται", "others.other": "{n} άλλες κλήσεις σας χρειάζονται", "others.list": "Κλήσεις που σας χρειάζονται: {list}",
    "floor.words": "Παύση: {who} πήρε τη φωνή.", "floor.another": "μια άλλη κλήση",
    "away.text": "λείπατε {t}", "away.audio": "{t} ήχου", "away.working": "Ο Claude εργάζεται ακόμα", "away.on": " στην ερώτηση «{q}»",
    "away.making": "Η φωνή δημιουργείται", "away.play.one": "Αναπαραγωγή της νέας απάντησης", "away.play.other": "Αναπαραγωγή των {n} νέων",
    "since.left": "Από τότε που φύγατε", "since.count": "{n} δεν ακούστηκαν", "since.play": "Αναπαραγωγή τους", "t.min": "{n} λ", "t.h": "{n} ώ", "t.d": "{n} ημ", "t.s": "{n} δ",
    "ann.arrived": "Έφτασε η απάντηση {n}", "ann.ended": "Η κλήση τελείωσε.", "ann.board": "Πίνακας: {text}.",
    "c.new.one": "Νέα απάντηση", "c.new.other": "{n} νέες απαντήσεις", "c.ended": "Έληξε", "c.stalled": "Κολλημένη", "c.answering": "Απαντά",
    "c.talking": "Μιλά τώρα", "c.waiting": "Σας περιμένει", "c.listening": "Ακούει", "c.playing": "Αναπαραγωγή",
    "c.here": "Εδώ · {word}", "c.thiscall": "αυτή η κλήση · ", "c.all": "Όλες οι κλήσεις", "c.open": "Άνοιγμα της «{topic}»", "c.next": "Επόμενη σε αναμονή",
    "c.label": "Κλήσεις: {text}. {words}", "c.newin": "Νέα απάντηση στην «{topic}».", "c.in": "{word} στην «{topic}»",
    "age.now": "τώρα", "age.m": "{n}λ", "age.h": "{n}ώ", "age.d": "{n}ημ", "tab.new": "Νέα",
  },
};
let uiLang = "en";          // the language the words are in now
function t(key, vars) {
  const s = (I18N[uiLang] && I18N[uiLang][key]) ?? I18N.en[key] ?? key;
  return vars ? s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? "")) : s;
}
// A count: the key's .one for 1, else .other; {n} is the count.
function tn(key, n, vars) { return t(key + (n === 1 ? ".one" : ".other"), {n, ...(vars || {})}); }
// The language of a text: Greek when its letters are mostly Greek, else English.
function languageOf(text) {
  const el = (text.match(/[Ͱ-Ͽἀ-῿]/g) || []).length, la = (text.match(/[A-Za-z]/g) || []).length;
  return el > la ? "el" : "en";
}
// The page's language: the choice in the settings; with Detect, the latest answer's language, else the browser's.
function pageLanguage() {
  if (language === "el" || language === "en") return language;
  for (let i = view.entries.length - 1; i >= 0; i--) { const e = view.entries[i]; if (e.who === "claude" && e.text) return languageOf(e.text); }
  return /^el\b/i.test(navigator.language || "") ? "el" : "en";
}
const T_ATTRS = {"data-t-aria": "aria-label", "data-t-tip": "data-tip", "data-t-title": "title", "data-t-ph": "placeholder"};
// Puts the words into every element that names a key; a language that has not changed leaves the page alone.
function translateStatic(root = document) {
  for (const el of root.querySelectorAll("[data-t]")) el.textContent = t(el.dataset.t);
  for (const [attr, to] of Object.entries(T_ATTRS)) {
    for (const el of root.querySelectorAll("[" + attr + "]")) el.setAttribute(to, t(el.getAttribute(attr)));
  }
}
function applyLang() {
  const now = pageLanguage();
  if (now === uiLang && document.documentElement.lang === now) return;
  uiLang = now; document.documentElement.lang = now;
  translateStatic();
  if (typeof relabelPage === "function") relabelPage();
}
applyLang();
