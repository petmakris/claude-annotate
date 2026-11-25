// Return and place (R): the welcome-back card (#welcome), the since-you-left divider (#sinceleft) in the list of earlier
// answers, the state-in-words strip (#statestrip), and the polite live region (#announcer). The batch R owns this file.
// Shared state declared here with let/const; markup goes into the slots call.html names. See the run's design notes.

// A new view arrived: `before` is the one it replaces. Where R sees new answers, a call that ended, a board that changed.
function returnOnView(before) {}
// The welcome-back card, from paintAll(): only after a real absence (the page hidden for some minutes, new answers since).
function paintWelcome() {}
// The state strip under the header: the call's state in words (and the other calls'), from paintAll().
function paintStateStrip() {}
// What the live region should say now, from paintAll(): the status, a new answer, a board change; it says each once.
function paintAnnounce() {}
// Say something once to a screen reader through #announcer: the polite live region. `text` is one short plain sentence.
function announce(text) {}
// The list of earlier answers has just placed its rows: `list` is #tllist. Put (or move, or remove) the since-you-left
// divider `li#sinceleft` before the first row whose answer was not heard; rows are .tlrow[data-id]. Called by paintEarlier().
function returnMarkEarlier(list) {}
