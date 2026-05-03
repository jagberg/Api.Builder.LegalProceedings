# Alias Matching

`alias_match_side(alias, parties)` in `scraper/matching.py` gates which
upstream results become court_listings vs similar_matches, and whether the
builder is stored as respondent or applicant.

Returns `'respondent'`, `'applicant'`, or `None`.

Rules (all must pass on the matched side):
1. **Both sides checked** — checks text after ` v ` (respondent) first, then before ` v ` (applicant). Respondent takes priority when both match.
2. **Word-boundary** — alias must appear as whole words (`(?<!\w)alias(?!\w)`)
3. **Company indicator** — single-word aliases (e.g. "Masterton") also require Pty/Ltd/Homes/etc. in the matched text; prevents matching personal surnames

```python
alias_match_side("Vogue Homes", parties)   # multi-word — boundary check only
alias_match_side("Dove", parties)           # single-word — also needs company indicator
```

Returns `None` when parties is None/empty or no side matches.

## How callers use the return value

**`scraper/main.py`** — scraper loop:
```python
side = alias_match_side(alias_name, listing["parties"])
if side is None:
    insert_similar_match(...)   # fuzzy — goes to similar_matches
else:
    upsert_listing(..., builder_is_applicant=(side == "applicant"))
```

**`app.py`** — live search path (`_split_exact_vs_fuzzy`):
- `'respondent'` → `hearings`
- `'applicant'` → `applicantCases`
- `None` → `similarMatches`
