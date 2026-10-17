Rank demand from this marketplace sample. Rank by week-over-week movement and buyer intent, not by raw volume.

Sample ({{market_scan.count}} listings):
{{market_scan.listings}}

Return JSON:
{"summary": "<one line>", "movers": [{"concept": "<adj> <subject> <product>", "wow_change_pct": <int>, "price_band": [low, high], "confidence": <0-100>}], "brief": {"concept": "...", "audience": "...", "angle": "...", "avoid": "..."}}
Pick at most 5 movers. The brief is for ONE original design concept; name the feeling and subject, never a specific existing listing.
