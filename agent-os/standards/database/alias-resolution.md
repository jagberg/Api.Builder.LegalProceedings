# Alias Resolution

Every builder lookup must resolve by canonical name OR any alias, case-insensitively.

```sql
SELECT DISTINCT b.id, b.builder_name
  FROM builders b
  LEFT JOIN builder_aliases ba ON ba.builder_id = b.id
 WHERE b.is_active = 1
   AND (LOWER(b.builder_name) = LOWER(%s) OR LOWER(ba.alias_name) = LOWER(%s))
```

- Always JOIN `builder_aliases` — querying `builders` alone misses alias-only searches
- Always use `DISTINCT` — multiple aliases on one builder produce duplicate rows without it
- Always use `LOWER()` on both sides — NSW API stores names in UPPERCASE; user searches are lowercase
- `court_listings.builder_id` always points to the parent builder, never an alias row
- Pass the search term twice: once for `b.builder_name`, once for `ba.alias_name`

## Fallback: resolve via hearing external_id

If name/alias lookup returns nothing, check whether the live search hits already exist
in `court_listings` under a different builder (e.g. "Masterton Homes Pty Ltd" vs stored "Masterton"):

```sql
SELECT DISTINCT b.id, b.builder_name
  FROM court_listings cl
  JOIN builders b ON b.id = cl.builder_id
 WHERE cl.external_id = ANY(%s) AND b.is_active = 1
```

If found, add the searched term as an alias and return that builder — never create a duplicate.
