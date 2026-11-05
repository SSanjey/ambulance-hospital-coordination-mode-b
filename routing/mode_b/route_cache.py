"""Bounded LRU route cache for Mode B.

Cache keys include algorithm identity, directed endpoints, graph version, and
condition version. Static, dynamic-condition, and time-aware routes must never
share cache entries because they optimize different objectives.

Run from the project root:
    python routing\\mode_b\\route_cache.py --self-test
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Hashable

CacheKey = tuple[str, Hashable, Hashable, str, str]
RouteResult = dict[str, Any]


SUPPORTED_ALGORITHMS = {"static_astar", "dynamic_astar", "time_astar"}


def file_content_version(path: str | Path) -> str:
    """Return a content hash suitable for small config files (e.g. conditions)."""
    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact_graph_version(metadata_path: str | Path) -> str:
    """Build a cheap graph-version identifier from compact-graph metadata.

    The graph builder records source graph size and modification time, avoiding
    a full hash of the large source JSON or memory-mapped arrays on each request.
    Rebuild the compact graph to update its metadata after changing the source.
    """
    path = Path(metadata_path)
    metadata = json.loads(path.read_text(encoding="utf-8"))
    required = (
        "vertex_count",
        "directed_edge_count",
        "graph_file_size_bytes",
        "graph_file_mtime_ns",
    )
    missing = [key for key in required if key not in metadata]
    if missing:
        raise ValueError(
            "Graph metadata is missing required version fields: " + ", ".join(missing)
        )
    packed = json.dumps(
        {key: metadata[key] for key in required},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


class LRURouteCache:
    """Least-recently-used cache with entry and total path-node bounds."""

    def __init__(self, max_entries: int = 32, max_total_path_nodes: int = 100_000) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        if max_total_path_nodes < 1:
            raise ValueError("max_total_path_nodes must be at least 1")
        self.max_entries = int(max_entries)
        self.max_total_path_nodes = int(max_total_path_nodes)
        self._items: OrderedDict[CacheKey, tuple[RouteResult, int]] = OrderedDict()
        self._total_path_nodes = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    @staticmethod
    def _key(
        algorithm: str,
        start_node: Hashable,
        goal_node: Hashable,
        graph_version: str,
        condition_version: str,
    ) -> CacheKey:
        normalized_algorithm = algorithm.strip().lower()
        if normalized_algorithm not in SUPPORTED_ALGORITHMS:
            supported = ", ".join(sorted(SUPPORTED_ALGORITHMS))
            raise ValueError(f"algorithm must be one of: {supported}")
        if not graph_version or not condition_version:
            raise ValueError("graph_version and condition_version must be non-empty strings")
        return (
            normalized_algorithm,
            start_node,
            goal_node,
            str(graph_version),
            str(condition_version),
        )

    def _remove_oldest(self) -> None:
        _key, (_result, path_nodes) = self._items.popitem(last=False)
        self._total_path_nodes -= path_nodes
        self.evictions += 1

    def get_or_compute(
        self,
        *,
        algorithm: str,
        start_node: Hashable,
        goal_node: Hashable,
        graph_version: str,
        condition_version: str,
        compute: Callable[[], RouteResult | None],
    ) -> tuple[RouteResult | None, bool, float]:
        """Return result, cache-hit flag, and elapsed cache-call time in ms.

        Successful route dictionaries containing a ``path`` list are cached.
        Failed/no-route results are not cached. The result is copied on cache
        insertion and retrieval so callers cannot mutate a stored path.
        """
        key = self._key(
            algorithm,
            start_node,
            goal_node,
            graph_version,
            condition_version,
        )
        started = time.perf_counter()
        stored = self._items.get(key)
        if stored is not None:
            self._items.move_to_end(key)
            self.hits += 1
            result = copy.deepcopy(stored[0])
            return result, True, (time.perf_counter() - started) * 1000.0

        self.misses += 1
        result = compute()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if result is None:
            return None, False, elapsed_ms
        if not isinstance(result, dict) or not isinstance(result.get("path"), list):
            raise TypeError("compute must return None or a dict containing a list under 'path'")

        result_copy = copy.deepcopy(result)
        path_nodes = len(result_copy["path"])
        # Oversized paths are returned correctly but deliberately not cached.
        if path_nodes == 0 or path_nodes > self.max_total_path_nodes:
            return result, False, elapsed_ms

        previous = self._items.pop(key, None)
        if previous is not None:
            self._total_path_nodes -= previous[1]

        while self._items and (
            len(self._items) >= self.max_entries
            or self._total_path_nodes + path_nodes > self.max_total_path_nodes
        ):
            self._remove_oldest()

        if path_nodes <= self.max_total_path_nodes:
            self._items[key] = (result_copy, path_nodes)
            self._total_path_nodes += path_nodes
        return result, False, elapsed_ms

    def clear(self) -> None:
        self._items.clear()
        self._total_path_nodes = 0

    def stats(self) -> dict[str, int]:
        return {
            "entries": len(self._items),
            "path_nodes_stored": self._total_path_nodes,
            "max_entries": self.max_entries,
            "max_total_path_nodes": self.max_total_path_nodes,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
        }


def _self_test() -> None:
    cache = LRURouteCache(max_entries=4, max_total_path_nodes=10)
    calls = {"count": 0}

    def route(path: list[int], distance: float) -> Callable[[], RouteResult]:
        def compute() -> RouteResult:
            calls["count"] += 1
            return {"path": path.copy(), "distance_km": distance, "elapsed_ms": 12.5}
        return compute

    # Initial calculation followed by exact-key reuse.
    first, first_hit, _ = cache.get_or_compute(
        algorithm="static_astar", start_node="V1", goal_node="V3",
        graph_version="graph-A", condition_version="static",
        compute=route([0, 1, 2], 2.0),
    )
    second, second_hit, _ = cache.get_or_compute(
        algorithm="static_astar", start_node="V1", goal_node="V3",
        graph_version="graph-A", condition_version="static",
        compute=route([9], 99.0),
    )
    assert not first_hit and second_hit
    assert first == second and second["path"] == [0, 1, 2]  # type: ignore[index]
    assert calls["count"] == 1

    # Different objectives and condition versions must never collide.
    _, dynamic_hit, _ = cache.get_or_compute(
        algorithm="dynamic_astar", start_node="V1", goal_node="V3",
        graph_version="graph-A", condition_version="conditions-A",
        compute=route([0, 2], 3.0),
    )
    _, timed_hit, _ = cache.get_or_compute(
        algorithm="time_astar", start_node="V1", goal_node="V3",
        graph_version="graph-A", condition_version="time-conditions-A",
        compute=route([0, 1, 2], 2.0),
    )
    _, changed_conditions_hit, _ = cache.get_or_compute(
        algorithm="dynamic_astar", start_node="V1", goal_node="V3",
        graph_version="graph-A", condition_version="conditions-B",
        compute=route([0, 1, 2], 2.0),
    )
    assert not dynamic_hit and not timed_hit and not changed_conditions_hit

    # Directed endpoints must be distinct; LRU eviction stays bounded.
    cache.get_or_compute(
        algorithm="static_astar", start_node="V3", goal_node="V1",
        graph_version="graph-A", condition_version="static",
        compute=route([2, 1, 0], 2.0),
    )
    stats = cache.stats()
    assert stats["entries"] <= 4 and stats["path_nodes_stored"] <= 10
    print("LRU route-cache self-test passed: hits, objective separation, condition-version separation and bounded eviction.")
    print("Verified: static_astar, dynamic_astar, and time_astar use separate cache identities.")
    print("No Tamil Nadu graph or Mode A files were opened or modified.")
    print("Cache stats:", stats)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Run synthetic cache tests only")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
