Turn the Research brief into a design prompt and product plan.

Brief: {{research.brief}}
Shop calendar: {{season}}
Product type for this run: {{product_type}} (the design must suit it: a mug wants a compact centred motif; a sweatshirt can carry a larger chest print; a tote likes bold simple shapes; a poster/art print is full-bleed wall art — a complete composition with a background, not an isolated motif, in a style people frame: watercolour, line art, vintage botanical, retro travel)
Style (mandatory): {{assigned_style}}
Design text from the brief (print exactly, or null): {{research.brief.text}}

The design_prompt must follow the style rules above. If there is text, the prompt must say: the design contains the exact words "<text>" — spelled exactly, every letter correct, nothing else written — and describe the lettering style; if there is no text, say "no text". Never ask for a shirt, mockup, person or background.

Return JSON: {"summary": "<one line>", "concept": "<short name>", "occasion": "<from the brief or none>", "style": "<style id>", "text": "<exact design text or null>", "design_prompt": "<prompt for the image model, following the style rules>", "products": ["{{product_type}}"]}
