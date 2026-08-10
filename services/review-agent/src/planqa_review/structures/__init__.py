from __future__ import annotations

from planqa_review.structures import bundled_screen_hybrid

# Registry of pluggable review structures for `experiment.run_experiment(review_fn=...)` and
# the CLI's `--structure` flag — baseline (제안5, models.PROFILES["gemini_lite"] through
# pipeline.review_document) isn't listed here since it's the default when no structure is given.
STRUCTURES = {
    "bundled_screen_hybrid": bundled_screen_hybrid.review_document,
}
