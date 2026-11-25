// Starts the page: everything above is loaded, so the first paint and the poll may begin. The core's file.
// Each batch's own start-up goes in its own file as a top-level statement (they run in file order, before this one);
// nothing here changes except to start a new part that needs the whole page to exist first.
applyTheme();
setMode("idle");
if (talkMode === "live") startLive();
if (matchMedia("(hover: hover) and (pointer: fine)").matches) $("text").focus();
claimPlayer(false);
poll();
