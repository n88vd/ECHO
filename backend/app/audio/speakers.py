"""Speaker clustering and identity matching on L2-normalised embeddings."""

import numpy as np


def cosine(a, b) -> float:
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na and nb else 0.0


def agglomerative(embs: list[list[float]], threshold: float) -> tuple[list[int], float]:
    """Average-linkage clustering with a cosine-similarity stop threshold.

    Returns (labels, confidence) where confidence is the margin between the
    weakest merge accepted and the strongest merge rejected (0..1)."""
    n = len(embs)
    if n == 0:
        return [], 1.0
    if n == 1:
        return [0], 1.0
    X = np.asarray(embs, dtype=np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
    clusters: list[list[int]] = [[i] for i in range(n)]
    sim = X @ X.T
    accepted: list[float] = []
    rejected_best = -1.0
    while len(clusters) > 1:
        best, bi, bj = -2.0, -1, -1
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                s = float(sim[np.ix_(clusters[i], clusters[j])].mean())
                if s > best:
                    best, bi, bj = s, i, j
        if best < threshold:
            rejected_best = best
            break
        accepted.append(best)
        clusters[bi] = clusters[bi] + clusters[bj]
        del clusters[bj]
    labels = [0] * n
    order = sorted(range(len(clusters)), key=lambda k: -len(clusters[k]))
    for new_label, k in enumerate(order):
        for idx in clusters[k]:
            labels[idx] = new_label
    margins = []
    if accepted:
        margins.append(min(accepted) - threshold)
    if rejected_best > -1.0:
        margins.append(threshold - rejected_best)
    margin = min(margins) if margins else 1.0
    return labels, float(max(0.0, min(1.0, margin * 4)))


def centroid(embs: list[list[float]]) -> list[float]:
    X = np.asarray(embs, dtype=np.float32)
    c = X.mean(axis=0)
    n = np.linalg.norm(c)
    return (c / n).tolist() if n else c.tolist()
