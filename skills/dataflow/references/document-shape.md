# dataflow document shape

Moved out of SKILL.md. Read it when writing `dataflow.draft.json`: it holds the full JSON shape and what each field means.

### Document shape

```json
{
  "seed": "OrderShare",
  "question": "how does a shared order get from the API to the database",
  "generated_ts": 0,
  "model": [
    "Sharing is stored as a row, but the *policy* that allows it is a JSON blob — two different persistence mechanics in one feature."
  ],
  "slices": [
    {
      "id": "share",
      "title": "Sharing an order",
      "question": "what happens when the user presses Share?",
      "nodes": [
        {"id": "ctl", "layer": "api", "role": "Controller",
         "name": "OrderShareController",
         "file": "src/main/java/com/acmeshop/api/OrderShareController.java", "line": 24,
         "summary": "The only HTTP way in or out of sharing.",
         "members": [
           {"text": "public ShareResultDto share(@PathVariable long id, @RequestBody ShareRequestDto body)",
            "line": 31, "tag": "POST",
            "detail": "Converts, then delegates. Returns the **re-read** result, not the payload it was handed."},
           {"text": "private final ShareService shareService", "line": 27}],
         "edges": [{"to": "conv", "label": "converts via"}]},

        {"id": "conv", "layer": "mapper", "role": "Mapper — has a file",
         "name": "ShareDtoConverter",
         "file": "src/main/java/com/acmeshop/api/convert/ShareDtoConverter.java", "line": 18,
         "summary": "reshapes `Map<Locale,String>` ⇄ `en` / `fr`",
         "edges": [{"to": "svc", "label": "feeds"}]},

        {"id": "orm", "layer": "mapper", "role": "Mapper — no file", "implicit": true,
         "name": "Hibernate @Embeddable",
         "file": "src/main/java/com/acmeshop/domain/ShareTarget.java", "line": 12,
         "summary": "three fields flatten into three columns",
         "note": "**There is no mapper class to open here.** The ORM generates it.",
         "edges": [{"to": "tbl", "label": "produces"}]},

        {"id": "tbl", "layer": "db", "role": "Table", "name": "order_shares",
         "flag": "no foreign key",
         "file": "src/main/resources/db/changelog/changelog-14-order-shares.xml", "line": 7,
         "summary": "share_id BIGINT `PK`\nshared_with VARCHAR(255)",
         "members": [{"text": "shared_with VARCHAR(255)", "line": 11}]}
      ]
    }
  ]
}
```

Field rules:

- `file` is **repository-relative** (no leading `/`, no `..`) and `line` is a
  real line. **Every node needs both** — the only way the reader reaches code
  is `POST /api/open`, so a node without an anchor is a dead end. For an
  implicit mapper, anchor the place the framework is configured.
- `id` is unique across the **whole** document — it is the thread anchor.
- `layer` is one of `api`, `mapper`, `application`, `domain`, `infra`, `db`.
  `mapper` nodes render on the arrow between their neighbours; every other
  layer is a box in the column. Order the nodes the way the request travels.
- `role` is the small label above the name: `Controller`, `DTO`, `Service`,
  `Domain`, `Repository`, `Table`, `Mapper — has a file`, `Mapper — no file`.
- `summary` is **one line** (180 chars max, enforced): what this node *is* and
  why it is on the path. **Never a list of its members** — the members list
  them, and a summary that repeats them makes the reader read the same
  endpoints twice and the node's own claim not at all.
- `members` are the body of the node — one row each, and the reader's index
  into the file:
  - `text` is the **real signature, copied from the source**, return type
    included: `public ResponseEntity<ShippingConfigDto> saveConfigForOrganization(ShippingConfigDto dto)`,
    not `saveConfigForOrganization(dto)`. The reader is looking for the line
    they are about to open; a paraphrase is not what they will find there.
  - `line` opens that exact line. Omit it only for a row that describes the
    node rather than sitting on one line.
  - `detail` is optional markdown that **makes the row expandable in place** —
    what this method does, what it calls, what surprises. Put it on the rows
    that carry the behaviour; a row with no detail stays a one-liner.
  - `tag` is an optional badge of at most 12 characters: `GET`, `PUT`,
    `@Transactional`, `throws`, `record`, `PK`.
  - `field` is an optional slug that makes the row **addressable by a route**
    (below). Give it to rows that carry one property: a record component, a
    column, a JSON key, or the expression that moves the value at that hop.
  - **One row per endpoint, per field, per column.** Do not merge two methods
    into one row, and do not add a row that summarises the other rows.
- `routes` (optional, top level) is what makes this a property tool rather
  than a class diagram. **A route is one property's path, expressed as an
  ordered list of rows that already exist** — selecting it dims the rest of
  the board, opens the nodes it passes through, and lights those rows. There
  is no second diagram.

  ```json
  "routes": [
    {"id": "code", "label": "code",
     "title": "InteractionChannelDto.code → client_interaction_channel",
     "note": "Seven hops and **two renames** — no grep follows that.",
     "hops": [{"node": "dto",  "field": "code"},
              {"node": "icm",  "field": "code", "fork": true},
              {"node": "ci",   "field": "channel", "rename": true},
              {"node": "tbl2", "field": "channel", "destination": true}]}
  ]
  ```

  - Every hop must resolve to a member row that declares that `field`, or the
    document is rejected — a hop that highlights nothing reads as the route
    being wrong about the code.
  - `rename: true` marks the hop where **the property changes name**. Those
    are the hops no grep and no "find usages" survives, and they are the
    reason the tool exists — never leave one unmarked.
  - `fork: true` marks a hop where one property becomes several, or where the
    path splits between slices.
  - `destination: true` marks a resting place: a column, a JSON key, or a
    decision the value is consumed by.
- `edges` point at other node ids, with a verb-ish `label`. Set `join: true`
  on an edge that crosses between slices; both nodes then show a ◆ JOIN badge.
- `flag` is a short amber warning on the node header: `no foreign key`,
  `no JPA entity`, `serialized blob`.
- `note` is the paragraph a reader would otherwise get wrong. Lead with the
  claim in bold. Omit it rather than pad it.
