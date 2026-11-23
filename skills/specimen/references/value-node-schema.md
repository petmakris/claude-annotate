# specimen.json value-node schema

Moved out of SKILL.md. Read it before writing `specimen.json`: it holds a full worked instance and why every level must match the real class.

The value-node schema, fixed by `document.py` and `build_items`:

```json
{
  "root": "com.example.analytics.model.AnalyticsResult",
  "instance": {
    "kind": "object",
    "type": "com.example.analytics.model.AnalyticsResult",
    "fields": {
      "charts": {
        "kind": "list",
        "element": "com.example.analytics.model.AnalyticsResult$Chart",
        "items": [
          {
            "kind": "object",
            "type": "com.example.analytics.model.AnalyticsResult$Chart",
            "fields": {
              "groupingClassificationId": { "kind": "scalar", "value": "54", "provenance": "captured" },
              "riskContributions": {
                "kind": "list",
                "element": "com.example.analytics.model.AnalyticsResult$CategoryRiskContribution",
                "items": [
                  {
                    "kind": "object",
                    "type": "com.example.analytics.model.AnalyticsResult$CategoryRiskContribution",
                    "fields": {
                      "category": { "kind": "scalar", "value": "1295", "provenance": "captured" },
                      "current": {
                        "kind": "object",
                        "type": "com.example.analytics.service.RiskContribution",
                        "fields": {
                          "totalContribution": { "kind": "scalar", "value": "0.0412", "provenance": "chosen" }
                        }
                      },
                      "proposed": { "kind": "null" }
                    }
                  }
                ]
              }
            }
          }
        ]
      },
      "totalWealthAfter": { "kind": "null" }
    }
  }
}
```

Every level in a specimen must be a level the real class actually has, checked
against `extract_types` output: in the example, `charts` is a `List<Chart>`,
`Chart.riskContributions` a `List<CategoryRiskContribution>`, and
`CategoryRiskContribution.current` is declared `RiskContribution` — an object with
its own fields, not a number. Skipping a level, or giving an object field a scalar,
puts values under `(type, field)` pairs that do not exist and the rows they belong to
stay empty.
