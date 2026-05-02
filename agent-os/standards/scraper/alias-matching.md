# Alias Matching

`alias_matches_parties(alias, parties)` in `scraper/matching.py` gates which
upstream results become court_listings vs similar_matches.

Rules (all must pass):
1. **Respondent-only** — only checks text after ` v ` in the parties string
2. **Word-boundary** — alias must appear as whole words (`(?<!\w)alias(?!\w)`)
3. **Company indicator** — single-word aliases (e.g. "Dove") also require Pty/Ltd/Homes/etc.
   in the respondent text; prevents matching personal surnames

```python
alias_matches_parties("Vogue Homes", parties)   # multi-word — boundary check only
alias_matches_parties("Dove", parties)           # single-word — also needs company indicator
```

Returns `False` when `parties` is None or empty.
