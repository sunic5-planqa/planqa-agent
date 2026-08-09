from __future__ import annotations

from planqa_review.structures import category_screen, cell3, cell3r, proposal0

# Registry of pluggable review structures for `experiment.run_experiment(review_fn=...)` —
# baseline (제안5, models.PROFILES["gemini_lite"] through pipeline.review_document) isn't
# listed here since it's the harness's own default when no review_fn is given.
STRUCTURES = {
    "proposal0": proposal0.review_document,
    "cell3": cell3.review_document,
    "cell3r": cell3r.review_document,
    "category_screen": category_screen.review_document,
}
