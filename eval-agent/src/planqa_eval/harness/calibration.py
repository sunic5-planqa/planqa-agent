from __future__ import annotations

import math
from typing import Any


def cohens_kappa(a: list, b: list) -> float:
    assert len(a) == len(b) and a, "need equal non-empty sequences"
    labels = sorted(set(a) | set(b), key=lambda x: str(x))
    idx = {label: i for i, label in enumerate(labels)}
    n = len(labels)
    mat = [[0] * n for _ in range(n)]
    for x, y in zip(a, b):
        mat[idx[x]][idx[y]] += 1
    total = len(a)
    observed = sum(mat[i][i] for i in range(n)) / total
    row = [sum(mat[i]) / total for i in range(n)]
    col = [sum(mat[i][j] for i in range(n)) / total for j in range(n)]
    expected = sum(row[i] * col[i] for i in range(n))
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


def spearman(a: list[float], b: list[float]) -> float:
    assert len(a) == len(b) and a

    def ranks(xs: list[float]) -> list[float]:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        i = 0
        while i < len(xs):
            j = i
            while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    ra, rb = ranks(a), ranks(b)
    mean_a = sum(ra) / len(ra)
    mean_b = sum(rb) / len(rb)
    num = sum((x - mean_a) * (y - mean_b) for x, y in zip(ra, rb))
    den_a = math.sqrt(sum((x - mean_a) ** 2 for x in ra))
    den_b = math.sqrt(sum((y - mean_b) ** 2 for y in rb))
    if den_a == 0 or den_b == 0:
        return 0.0
    return num / (den_a * den_b)


def is_numeric(xs: list) -> bool:
    try:
        [float(x) for x in xs]
        return True
    except (TypeError, ValueError):
        return False


def compare_label_sets(reference: dict[str, dict[str, Any]], candidate: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """QC diagnostic, not a gate: how well do two label sets agree on their shared fields?
    Used to check ensemble-internal agreement, not to validate against human ground truth."""
    common_keys = sorted(set(reference) & set(candidate))
    fields: dict[str, Any] = {}
    if common_keys:
        field_names: set[str] = set()
        for key in common_keys:
            field_names |= set(reference[key]) & set(candidate[key])
        for field_name in sorted(field_names):
            pairs = [
                (reference[key][field_name], candidate[key][field_name])
                for key in common_keys
                if reference[key][field_name] is not None and candidate[key][field_name] is not None
            ]
            if not pairs:
                continue
            ref_vals, cand_vals = zip(*pairs)
            agreement = sum(1 for r, c in zip(ref_vals, cand_vals) if str(r) == str(c)) / len(pairs)
            if is_numeric(ref_vals) and is_numeric(cand_vals):
                metric, value = "spearman", spearman([float(v) for v in ref_vals], [float(v) for v in cand_vals])
            else:
                metric, value = "kappa", cohens_kappa(list(ref_vals), list(cand_vals))
            fields[field_name] = {"metric": metric, "value": value, "agreement": agreement, "n": len(pairs)}
    return {"n": len(common_keys), "fields": fields}
