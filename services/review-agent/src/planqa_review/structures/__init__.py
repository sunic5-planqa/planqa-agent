from __future__ import annotations

from planqa_review.structures import category_screen

# Registry of pluggable review structures for `experiment.run_experiment(review_fn=...)` and
# the CLI's `--structure` flag — baseline (제안5, models.PROFILES["gemini_lite"] through
# pipeline.review_document) isn't listed here since it's the default when no structure is given.
STRUCTURES = {
    "category_screen": category_screen.review_document,
}
