Rank demand from this marketplace sample. Rank by week-over-week movement and buyer intent, not by raw volume.

Sample ({{market_scan.count}} listings; if zero, rank the categories below from your own knowledge of what sells steadily as gifts):
{{market_scan.listings}}
Categories: {{market_scan.categories}}
Shop calendar — buyers shop for occasions weeks ahead; a design must be live before they start looking: {{season}}
Product type this brief will be made as (chosen by rotation): {{product_type}}
Design style for this listing (assigned by rotation/what sells — mandatory): {{assigned_style}}
All styles the shop makes, for context: {{style_library}}
Sales per style so far (listings, sales, revenue): {{style_results}}
Station's proven winners (make fresh variations on these before chasing new ground): {{winners}}
Mother's recent notes: {{memory.notes}}

Return JSON:
{"summary": "<one line>", "movers": [{"concept": "<adj> <subject> <product>", "wow_change_pct": <int>, "price_band": [low, high], "confidence": <0-100>}], "brief": {"concept": "...", "audience": "...", "angle": "...", "avoid": "..."}}
Pick at most 5 movers. The brief is for ONE original design concept; name the feeling and subject, never a specific existing listing. When an occasion in the calendar says "design now" or "last call", at least the brief (and most movers) should serve it — a gift for a specific person ("for my plant-obsessed mom") beats a generic seasonal motif. Add "occasion": "<name or none>" to the brief. Add "style": "<the assigned style id>". If the style uses text, add "text": the exact words on the design — 1 to 6 words, a line a buyer would wear or give (an identity, a joke, a place, a quote; no brand, song lyric, character or trademark; spell it exactly as it should print). If the style has no text, "text": null.
