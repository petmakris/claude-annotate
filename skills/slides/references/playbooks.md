# Playbooks

Moved out of SKILL.md. Read it when you have found the reference deck and must decide what the new deck should say.

### Then: is there a playbook for this deck?

`components.md` says how a slide is drawn. It does not say what a slide should **say** —
that belongs to the meeting the deck is for, and it differs per meeting.

**Playbooks live with the decks, not in this skill.** A playbook carries one meeting's
audience, slot length and section order — none of which transfers to a different room —
so it belongs beside the decks it governs, at `$DECKS/playbooks/<meeting-slug>/`. Keeping
them out of the skill also keeps the skill about *how a slide is drawn*, which is the only
thing that is true for every deck. Look for one next to the decks:

```bash
ls "$DECKS"/playbooks/ 2>/dev/null || echo "no playbooks in this decks folder"
```

If a folder there matches the meeting this deck is for, read its `PLAYBOOK.md` before
writing any content, and follow whatever else it points at. If there is none, ask the
user what the meeting expects, and offer to write a playbook into
`$DECKS/playbooks/<meeting-slug>/` if it is a meeting that recurs.

Never fold a playbook into this skill. A
playbook names real people and a real audience; the skill is generic and gets read in
full on every invocation. Keep the boundary.
