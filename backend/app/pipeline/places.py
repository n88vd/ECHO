"""Place clustering (DBSCAN on haversine distance) and travel detection."""

import math
from collections.abc import Sequence

EARTH_M = 6_371_000.0


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(h))


def dbscan(points: Sequence[tuple[float, float]], eps_m: float = 75.0, min_pts: int = 3) -> list[int]:
    n = len(points)
    labels = [-2] * n
    cid = -1
    neigh = [[j for j in range(n) if haversine_m(points[i], points[j]) <= eps_m] for i in range(n)]
    for i in range(n):
        if labels[i] != -2:
            continue
        if len(neigh[i]) < min_pts:
            labels[i] = -1
            continue
        cid += 1
        labels[i] = cid
        queue = list(neigh[i])
        while queue:
            j = queue.pop()
            if labels[j] == -1:
                labels[j] = cid
            if labels[j] != -2:
                continue
            labels[j] = cid
            if len(neigh[j]) >= min_pts:
                queue.extend(neigh[j])
    return labels


def max_speed_kmh(fixes: Sequence[tuple[float, float, float]]) -> float:
    """fixes: (epoch_seconds, lat, lng) sorted by time."""
    best = 0.0
    for (t1, la1, lo1), (t2, la2, lo2) in zip(fixes, fixes[1:], strict=False):
        dt = t2 - t1
        if dt < 20:
            continue
        best = max(best, haversine_m((la1, lo1), (la2, lo2)) / dt * 3.6)
    return best


def label_home_work(visits: Sequence[tuple[int, int, bool]]) -> str | None:
    """visits: (local_hour, weekday 0=Mon, _) for one place cluster. Returns 'Home', 'Work' or None."""
    if len(visits) < 5:
        return None
    night = sum(1 for h, _, _ in visits if h >= 21 or h < 7)
    work = sum(1 for h, d, _ in visits if 9 <= h < 18 and d < 5)
    if night / len(visits) >= 0.5:
        return "Home"
    if work / len(visits) >= 0.6:
        return "Work"
    return None
