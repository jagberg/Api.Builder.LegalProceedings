# Alias Resolution

Every builder lookup must resolve by canonical name OR any alias.

```sql
SELECT DISTINCT b.id, b.builder_name
  FROM builders b
  LEFT JOIN builder_aliases ba ON ba.builder_id = b.id
 WHERE b.is_active = 1
   AND (b.builder_name = %s OR ba.alias_name = %s)
```

- Always JOIN `builder_aliases` — querying `builders` alone misses alias-only searches
- Always use `DISTINCT` — multiple aliases on one builder produce duplicate rows without it
- `court_listings.builder_id` always points to the parent builder, never an alias row
- Pass the search term twice: once for `b.builder_name`, once for `ba.alias_name`
