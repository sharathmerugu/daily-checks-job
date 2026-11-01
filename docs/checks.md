# Check kinds

A check is declared on a dataset with a `name`, a `kind`, the `field` it reads and the
`params` its kind takes. `app/declarations.py` validates declarations; `jobs/run_checks.py`
evaluates them. Each check gives one result per record of its dataset.

## completeness

A record passes when the field is present and its value is neither null nor blank (empty
or only whitespace).

Params: none.

```json
{"name": "email present", "kind": "completeness", "field": "email"}
```

## accuracy

A record passes when the value is one of the declared `allowed` values or, for a numeric
check, between `min` and `max` inclusive (either bound may be left out). A check declares
either `allowed` or a range (`min`, `max` or both), never both.

Params: `allowed` (list of strings), or `min` and/or `max` (numbers).

```json
{"name": "country known", "kind": "accuracy", "field": "country", "params": {"allowed": ["US", "GB"]}}
{"name": "amount in range", "kind": "accuracy", "field": "amount", "params": {"min": 0, "max": 10000}}
```

## timeliness

A record passes when the value, an ISO 8601 timestamp, is no more than `max_age_hours`
before 00:00 UTC on the run's date.

Params: `max_age_hours` (positive integer).

```json
{"name": "updated in the last 24 hours", "kind": "timeliness", "field": "updated_at", "params": {"max_age_hours": 24}}
```

## uniqueness

A record passes when no other record in the same dataset has the same value in the field.
Every record sharing a value fails, not only the later ones. A missing or null value fails as
missing and is never counted as a duplicate. Values are compared as JSON values, strictly:
`1`, `1.0`, `"1"` and `true` are all different, strings are case- and whitespace-sensitive
(`""` is a value like any other), and lists and objects are compared by content (key order
in an object does not matter).

Params: none.

```json
{"name": "customer id unique", "kind": "uniqueness", "field": "customer_id"}
```
