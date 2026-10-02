/* wc-threads.js — shared derivation from the daemon's raw thread-bulk shape
   ({anchor: {anchor, version, messages, title?, anchor_text?}}) to the
   flattened per-anchor render info every migrated skill's static JS expects
   ({latest_synthesis, question, title, version, updated_at}).

   Every skill's Claude-authored messages use role "agent" (the daemon's own
   default — see the cutover plan's Global Constraints); "user" marks the
   human's own submitted questions. A thread with no agent message yet is
   OMITTED from the result, matching every skill's own prior behavior: the
   page owns "pending" state for a question it just submitted, and an empty
   entry would overwrite that with nothing.
*/
(function (global) {
  "use strict";

  function derive(rawThreadsBulk) {
    const out = {};
    for (const anchor of Object.keys(rawThreadsBulk || {})) {
      const t = rawThreadsBulk[anchor];
      const messages = (t && t.messages) || [];
      const agentMsgs = messages.filter((m) => m.role === "agent");
      if (agentMsgs.length === 0) continue;
      const userMsgs = messages.filter((m) => m.role === "user");
      const last = agentMsgs[agentMsgs.length - 1];
      out[anchor] = {
        latest_synthesis: last.text || "",
        version: t.version || 0,
        updated_at: last.ts || 0,
        title: t.title || "",
        question: userMsgs.length ? userMsgs[userMsgs.length - 1].text || "" : "",
      };
    }
    return out;
  }

  global.WcThreads = { derive: derive };
})(typeof window !== "undefined" ? window : this);
