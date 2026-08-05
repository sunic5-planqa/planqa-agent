- Title: Assume the review agent's JSON output matches the common Issue schema directly
- Status: Draft
- Date: 2026-08-02
- Context: The PlanQA evaluation agent's Parser needs to normalize the review (검토) agent's
  JSON output into the common schema — `{doc_id, level, rule_id, location, description,
  exception_ref}` — the same schema the golden dataset and Review1-6 sheets are normalized
  into. No real sample of the review agent's output exists yet (it's a separate,
  in-progress deliverable), so there is nothing to parse against.
- Options:
  1. Block Parser's JSON-input path until a real sample exists.
  2. Assume the review agent emits the common schema's own field names directly (a JSON
     array, optionally wrapped in `{"issues": [...]}`), build against that, and adjust
     later if the real format differs.
  3. Design a more elaborate, defensive field-alias mapping layer up front to hedge against
     an unknown format.
- Decision: Option 2. `parsers/review_json.py` expects:
  ```json
  [
    {
      "doc_id": "DOC-001",
      "level": "Document",
      "rule_id": "LG-06",
      "location": "3장 KPI vs 4장 기술 제약",
      "description": "...",
      "exception_ref": null,
      "issue_id": "optional, used to cross-reference the 2-1 gate's human blind labels"
    }
  ]
  ```
  or the same array under `{"issues": [...]}`.
- Consequences: If the real review agent's output differs, only `parsers/review_json.py`
  needs to change — every other module (Matcher, Verifier, Judge, Aggregator, Reporter)
  consumes `Issue` objects, not raw JSON, so the blast radius of being wrong here is one
  file. `issue_id` should be requested from whoever builds the review agent, since the 2-1
  confidence gate's human-vs-machine comparison (`harness/confidence_gate.py`) matches by
  it.
