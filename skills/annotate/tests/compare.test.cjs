#!/usr/bin/env node
/*
 * Behavioural tests for the compare kind's line diff (static/compare.js):
 * the rows a split view draws, asserted on directly.
 *
 * Run:  node skills/annotate/tests/compare.test.cjs
 * (also run by pytest via test_compare.py, which skips if node is absent)
 */
const path = require("path");
const C = require(path.join(__dirname, "..", "static", "compare.js"));

let failures = 0, ran = 0;
function test(name, fn) {
  ran++;
  try { fn(); process.stdout.write("  ok   " + name + "\n"); }
  catch (e) { failures++; process.stdout.write("  FAIL " + name + "\n         " + e.message + "\n"); }
}
function eq(actual, expected, what) {
  const a = JSON.stringify(actual), b = JSON.stringify(expected);
  if (a !== b) throw new Error((what || "") + " expected " + b + ", got " + a);
}

// One row as "<left>|<right>": t:n per side, "." for a filler.
const cell = (c) => (c ? c.t[0] + c.n : ".");
const shape = (rows) => rows.map((r) => cell(r.left) + "|" + cell(r.right));

test("a trailing newline is the end of the last line, not another line", () => {
  eq(C.splitLines("a\nb\n"), ["a", "b"]);
  eq(C.splitLines(""), []);
  eq(C.splitLines("a\r\nb"), ["a", "b"]);
});

test("identical code is every line on both sides, unchanged", () => {
  eq(shape(C.alignLines("a\nb\nc", "a\nb\nc")), ["s1|s1", "s2|s2", "s3|s3"]);
});

test("a changed line sits beside what replaced it", () => {
  eq(shape(C.alignLines("a\nB\nc", "a\nX\nc")), ["s1|s1", "d2|a2", "s3|s3"]);
});

test("a longer removed run faces fillers once the added run is used up", () => {
  eq(shape(C.alignLines("a\n1\n2\n3\nz", "a\nX\nz")),
     ["s1|s1", "d2|a2", "d3|.", "d4|.", "s5|s3"]);
});

test("an insertion between unchanged lines faces a filler on the left", () => {
  eq(shape(C.alignLines("a\nb", "a\nnew\nb")), ["s1|s1", ".|a2", "s2|s3"]);
});

test("unchanged lines after a change keep both sides' own numbers", () => {
  const rows = C.alignLines("x\ny\nk", "q\nk");
  eq(shape(rows), ["d1|a1", "d2|.", "s3|s2"]);
  eq([rows[2].left.text, rows[2].right.text], ["k", "k"]);
});

test("a new file is every line added with nothing on the left", () => {
  eq(shape(C.alignLines("", "a\nb")), [".|a1", ".|a2"]);
  eq(shape(C.alignLines("a\nb", "")), ["d1|.", "d2|."]);
});

test("both sides have the same number of rows, whatever the change", () => {
  const before = "public static Entry<Status, List<Task>> tasksOf(Status status, Task... tasks) {\n"
    + "    var taskList = Arrays.asList(tasks);\n"
    + "    if (taskList.stream().anyMatch(Objects::isNull)) {\n"
    + "        throw new IllegalArgumentException(\"A null task has been passed for a status. Fix the workflow.\");\n"
    + "    }\n"
    + "    return new SimpleEntry<>(status, taskList);\n"
    + "}\n";
  const after = "public static Map<Status, List<Task>> defineTasks(Function<Status, List<Task>> tasksPerStatus) {\n"
    + "    return Arrays.stream(Status.values()).collect(Collectors.toMap(status -> status, tasksPerStatus));\n"
    + "}\n";
  const rows = C.alignLines(before, after);
  eq(shape(rows), ["d1|a1", "d2|a2", "d3|.", "d4|.", "d5|.", "d6|.", "s7|s3"]);
  // Every line of each side appears once, in order.
  eq(rows.filter((r) => r.left).map((r) => r.left.n), [1, 2, 3, 4, 5, 6, 7]);
  eq(rows.filter((r) => r.right).map((r) => r.right.n), [1, 2, 3]);
});

test("a runaway diff falls back to one removed run beside one added run", () => {
  const a = Array.from({ length: 1500 }, (_, i) => "a" + i).join("\n");
  const b = Array.from({ length: 1500 }, (_, i) => "b" + i).join("\n");
  const rows = C.alignLines("keep\n" + a + "\nend", "keep\n" + b + "\nend");
  eq(rows.length, 1502);
  eq(shape([rows[0], rows[1], rows[1501]]), ["s1|s1", "d2|a2", "s1502|s1502"]);
});

process.stdout.write(`\n${ran - failures}/${ran} passed\n`);
process.exit(failures ? 1 : 0);
