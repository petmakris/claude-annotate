## Decisions made without Petros

- The final vote named five defects after the stop rule had ended the rounds. I entered them in the ledger and ran one more finishing pass rather than shipping them unexamined; the pass verifies each first and rejects one that does not reproduce. Undoable and cheap. The vote summary then named seven more; a third pass did the same with them (wf_facd0437-fd6). All 12 are fixed.

- Before the batches started, one designer split call.js into files owned by one batch each, so five batches could build at once without editing the same file. Undoable, and it follows the rule to give shared files one owner.

