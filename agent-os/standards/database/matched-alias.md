# matched_alias Traceability

Every `court_listings` row stores `matched_alias` — the alias string that was
searched when the listing was first surfaced.

- Tells you which trading name triggered a match (e.g. "Capitol Constructions"
  for a case with "Vogue Homes t/as Capitol Constructions" in the parties field)
- Set at upsert time, never updated — it records how the listing was *discovered*
- Always pass `matched_alias` to `upsert_listing()` and `insert_similar_match()`
