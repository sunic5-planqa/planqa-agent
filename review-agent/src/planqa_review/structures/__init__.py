from __future__ import annotations

from planqa_review.structures import (
    bundled_fewshot,
    bundled_verdict,
    category_fewshot,
    category_screen,
    cell3,
    cell3r,
    direct_verdict,
    paragraph_verdict,
    proposal0,
)

# Registry of pluggable review structures for `experiment.run_experiment(review_fn=...)` —
# baseline (제안5, models.PROFILES["gemini_lite"] through pipeline.review_document) isn't
# listed here since it's the harness's own default when no review_fn is given.
STRUCTURES = {
    "proposal0": proposal0.review_document,
    "cell3": cell3.review_document,
    "cell3r": cell3r.review_document,
    "category_screen": category_screen.review_document,
    "direct_verdict": direct_verdict.review_document,
    "paragraph_verdict": paragraph_verdict.review_document,
    "category_fewshot": category_fewshot.review_document,
    "bundled_verdict": bundled_verdict.review_document,
    "bundled_fewshot": bundled_fewshot.review_document,
}
