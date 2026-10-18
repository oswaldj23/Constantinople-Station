Rank demand from this marketplace sample. Rank by week-over-week movement and buyer intent, not by raw volume.

Sample ({{market_scan.count}} listings; if zero, rank the categories below from your own knowledge of what sells steadily as gifts):
{{market_scan.listings}}
Categories: {{market_scan.categories}}
Shop calendar — buyers shop for occasions weeks ahead; a design must be live before they start looking: {{season}}
Product type this brief will be made as (chosen by rotation): {{product_type}}
Station's proven winners (make fresh variations on these before chasing new ground): {{winners}}
Mother's recent notes: {{memory.notes}}

Return JSON:
{"summary": "<one line>", "movers": [{"concept": "<adj> <subject> <product>", "wow_change_pct": <int>, "price_band": [low, high], "confidence": <0-100>}], "brief": {"concept": "...", "audience": "...", "angle": "...", "avoid": "..."}}
Pick at most 5 movers. The brief is for ONE original design concept; name the feeling and subject, never a specific existing listing. When an occasion in the calendar says "design now" or "last call", at least the brief (and most movers) should serve it — a gift for a specific person ("for my plant-obsessed mom") beats a generic seasonal motif. Add "occasion": "<name or none>" to the brief.
