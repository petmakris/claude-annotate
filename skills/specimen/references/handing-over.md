# Handing over a specimen page

Moved out of SKILL.md. Read it when giving the person the URL: it says what to tell them about the tree and table views.

The page opens as a tree. Appending `#table` to the URL opens the same document as one
table per type instead, a row per instance and a column per field — the view for reading
three contributors under each other. A field whose value is an object is a column that
opens into its own fields, to any depth, so a value three levels down still lands in a
real column; `#table/all` opens every one of them. Say so when handing the URL over,
along with the fact that `✻` is how a question gets asked, on a row in the tree and on a
column header in the table; clicking a row or a header itself only opens and closes it.
Every type name on the page is a pill that copies its fully qualified name, with the
nested-class `$` written as a dot, which is the form an IDE's class search accepts.
