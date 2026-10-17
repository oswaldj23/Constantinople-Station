Rank demand from this marketplace sample. Rank by week-over-week movement and buyer intent, not by raw volume.

Sample ({{market_scan.count}} listings; if zero, rank the categories below from your own knowledge of what sells steadily as gifts):
{{market_scan.listings}}
Categories: {{market_scan.categories}}
Station's proven winners (make fresh variations on these before chasing new ground): {{winners}}
Mother's recent notes: {{memory.notes}}

Return JSON:
{"summary": "<one line>", "movers": [{"concept": "<adj> <subject> <product>", "wow_change_pct": <int>, "price_band": [low, high], "confidence": <0-100>}], "brief": {"concept": "...", "audience": "...", "angle": "...", "avoid": "..."}}
Pick at most 5 movers. The brief is for ONE original design concept; name the feeling and subject, never a specific existing listing.
