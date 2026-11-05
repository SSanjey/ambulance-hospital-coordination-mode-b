"""Memory-conscious KD-Tree index for the Tamil Nadu road graph.

This module streams only the top-level ``vertices`` object from the large graph
JSON. It never calls json.load() on the entire 493 MB graph. The resulting
NumPy arrays are saved separately and memory-mapped when the index is loaded.

Usage (from the project root):
    python routing\\mode_b\\kdtree_index.py --self-test
    python routing\\mode_b\\kdtree_index.py --build
    python routing\\mode_b\\kdtree_index.py --query 13.0827 80.2707

The --build command reads the full vertices section and may take some time.
It does not load the graph's adjacency section.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from array import array
from pathlib import Path
from typing import Any, Iterator, TextIO

import numpy as np
from scipy.spatial import cKDTree

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GRAPH = PROJECT_ROOT / "routing" / "tamil_nadu_graph.json"
DEFAULT_INDEX_DIR = PROJECT_ROOT / "routing" / "mode_b" / "kdtree_data"
EARTH_RADIUS_KM = 6371.0088
VERTEX_ID_PATTERN = re.compile(r"^V([0-9]+)$")


class _JSONStream:
    """Tiny streaming JSON tokenizer sufficient to read one top-level value."""

    def __init__(self, file_obj: TextIO, chunk_size: int = 1024 * 1024) -> None:
        self.file_obj = file_obj
        self.chunk_size = chunk_size
        self.buffer = ""
        self.pos = 0
        self.eof = False
        self.decoder = json.JSONDecoder()

    def _fill(self) -> None:
        if self.pos:
            self.buffer = self.buffer[self.pos:]
            self.pos = 0
        chunk = self.file_obj.read(self.chunk_size)
        if chunk:
            self.buffer += chunk
        else:
            self.eof = True

    def _ensure_char(self) -> None:
        while self.pos >= len(self.buffer) and not self.eof:
            self._fill()
        if self.pos >= len(self.buffer):
            raise EOFError("Unexpected end of JSON file")

    def skip_ws(self) -> None:
        while True:
            while self.pos < len(self.buffer) and self.buffer[self.pos].isspace():
                self.pos += 1
            if self.pos < len(self.buffer) or self.eof:
                return
            self._fill()

    def peek(self) -> str:
        self.skip_ws()
        self._ensure_char()
        return self.buffer[self.pos]

    def expect(self, expected: str) -> None:
        actual = self.peek()
        if actual != expected:
            raise ValueError(f"Expected {expected!r} at JSON stream position, got {actual!r}")
        self.pos += 1

    def read_value(self) -> Any:
        self.skip_ws()
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.pos)
                self.pos = end
                return value
            except json.JSONDecodeError:
                if self.eof:
                    raise
                old_len = len(self.buffer)
                self._fill()
                if self.eof and len(self.buffer) == old_len:
                    raise


def iter_graph_vertices(graph_path: Path) -> Iterator[tuple[int, float, float]]:
    """Yield (numeric vertex ID, latitude, longitude) without loading graph JSON.

    The known project graph uses vertex IDs such as ``V123`` and records with
    ``latitude`` and ``longitude`` fields. The parser also checks this format
    and raises an informative error if it differs.
    """
    with graph_path.open("r", encoding="utf-8") as file_obj:
        stream = _JSONStream(file_obj)
        stream.expect("{")
        found_vertices = False

        while True:
            token = stream.peek()
            if token == "}":
                break
            key = stream.read_value()
            if not isinstance(key, str):
                raise ValueError("Expected a string key in top-level graph JSON")
            stream.expect(":")

            if key != "vertices":
                # The metadata property is small. We must not call read_value on
                # adjacency, since that would parse the entire large graph.
                if key == "adjacency":
                    raise ValueError("Graph key 'adjacency' appeared before 'vertices'; safe streaming order assumption failed")
                stream.read_value()
                stream.skip_ws()
                if stream.peek() == ",":
                    stream.expect(",")
                continue

            found_vertices = True
            stream.expect("{")
            while True:
                token = stream.peek()
                if token == "}":
                    stream.expect("}")
                    break

                vertex_id = stream.read_value()
                if not isinstance(vertex_id, str):
                    raise ValueError(f"Expected string vertex ID, got {type(vertex_id).__name__}")
                match = VERTEX_ID_PATTERN.fullmatch(vertex_id)
                if not match:
                    raise ValueError(f"Unsupported vertex ID {vertex_id!r}; expected IDs like 'V123'")
                stream.expect(":")
                coordinate = stream.read_value()
                if not isinstance(coordinate, dict):
                    raise ValueError(f"Coordinates for {vertex_id} are not a JSON object")
                try:
                    latitude = float(coordinate["latitude"])
                    longitude = float(coordinate["longitude"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid coordinates for {vertex_id}") from exc
                if not math.isfinite(latitude) or not -90 <= latitude <= 90:
                    raise ValueError(f"Invalid latitude for {vertex_id}: {latitude}")
                if not math.isfinite(longitude) or not -180 <= longitude <= 180:
                    raise ValueError(f"Invalid longitude for {vertex_id}: {longitude}")
                yield int(match.group(1)), latitude, longitude

                token = stream.peek()
                if token == ",":
                    stream.expect(",")
                elif token == "}":
                    stream.expect("}")
                    break
                else:
                    raise ValueError(f"Unexpected token {token!r} after vertex {vertex_id}")
            return

        if not found_vertices:
            raise ValueError("The graph JSON does not contain a top-level 'vertices' object")


def _to_unit_sphere(latitude_degrees: np.ndarray, longitude_degrees: np.ndarray) -> np.ndarray:
    lat = np.deg2rad(latitude_degrees)
    lon = np.deg2rad(longitude_degrees)
    cos_lat = np.cos(lat)
    return np.column_stack((cos_lat * np.cos(lon), cos_lat * np.sin(lon), np.sin(lat)))


def build_index(graph_path: Path = DEFAULT_GRAPH, index_dir: Path = DEFAULT_INDEX_DIR) -> int:
    """Stream graph vertices into compact .npy files; return vertex count."""
    if not graph_path.is_file():
        raise FileNotFoundError(f"Road graph not found: {graph_path}")
    index_dir.mkdir(parents=True, exist_ok=True)

    # array.array stores compact C-style values; it avoids millions of Python
    # float and string objects while collecting vertex records.
    id_buffer = array("i")
    lat_buffer = array("d")
    lon_buffer = array("d")
    count = 0
    last_report = 0
    print(f"Streaming vertices from: {graph_path}")
    for vertex_num, latitude, longitude in iter_graph_vertices(graph_path):
        if vertex_num > 2_147_483_647:
            raise ValueError("Vertex numeric ID exceeds signed 32-bit range")
        id_buffer.append(vertex_num)
        lat_buffer.append(latitude)
        lon_buffer.append(longitude)
        count += 1
        if count - last_report >= 100_000:
            print(f"  Read {count:,} vertices...")
            last_report = count

    if not count:
        raise ValueError("No vertices were read from the graph")

    ids = np.frombuffer(id_buffer, dtype=np.int32)
    latitudes = np.frombuffer(lat_buffer, dtype=np.float64)
    longitudes = np.frombuffer(lon_buffer, dtype=np.float64)

    # Verify IDs are unique. Keep the check compact and sort only the IDs.
    sorted_ids = np.sort(ids)
    if np.any(sorted_ids[1:] == sorted_ids[:-1]):
        raise ValueError("Duplicate numeric vertex IDs detected")

    np.save(index_dir / "vertex_ids.npy", ids)
    np.save(index_dir / "latitudes.npy", latitudes)
    np.save(index_dir / "longitudes.npy", longitudes)

    xyz = _to_unit_sphere(latitudes, longitudes)
    np.save(index_dir / "xyz_unit_sphere.npy", xyz)
    del xyz, sorted_ids, ids, latitudes, longitudes

    print(f"Index source prepared: {count:,} vertices")
    print(f"Index files saved to: {index_dir}")
    print("This step indexed coordinates only; road adjacency was not loaded.")
    return count


class KDTreeVertexIndex:
    """Load the saved coordinate index using memory-mapped .npy arrays."""

    def __init__(self, index_dir: Path = DEFAULT_INDEX_DIR) -> None:
        required = ("vertex_ids.npy", "latitudes.npy", "longitudes.npy", "xyz_unit_sphere.npy")
        missing = [name for name in required if not (index_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(
                "KD-Tree index files are missing: " + ", ".join(missing) +
                ". Run this script with --build first."
            )
        self.index_dir = index_dir
        self.vertex_ids = np.load(index_dir / "vertex_ids.npy", mmap_mode="r")
        self.latitudes = np.load(index_dir / "latitudes.npy", mmap_mode="r")
        self.longitudes = np.load(index_dir / "longitudes.npy", mmap_mode="r")
        xyz = np.load(index_dir / "xyz_unit_sphere.npy", mmap_mode="r")
        self.tree = cKDTree(xyz, compact_nodes=True, balanced_tree=True, copy_data=False)
        self._xyz = xyz
        n = len(self.vertex_ids)
        if not (len(self.latitudes) == len(self.longitudes) == len(self._xyz) == n):
            raise ValueError("KD-Tree index arrays have inconsistent lengths")

    @staticmethod
    def _query_xyz(latitude: float, longitude: float) -> np.ndarray:
        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise ValueError("Latitude must be between -90 and 90")
        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise ValueError("Longitude must be between -180 and 180")
        return _to_unit_sphere(np.asarray([latitude]), np.asarray([longitude]))[0]

    def query(self, latitude: float, longitude: float, k: int = 1) -> list[dict[str, Any]]:
        """Return up to k nearest vertices, ordered by great-circle distance."""
        if not isinstance(k, int) or k < 1:
            raise ValueError("k must be a positive integer")
        query_xyz = self._query_xyz(float(latitude), float(longitude))
        k = min(k, len(self.vertex_ids))
        chord_distances, indices = self.tree.query(query_xyz, k=k)
        chord_distances = np.atleast_1d(chord_distances)
        indices = np.atleast_1d(indices)
        results: list[dict[str, Any]] = []
        for chord, index in zip(chord_distances, indices):
            index = int(index)
            arc = 2.0 * math.asin(min(1.0, max(0.0, float(chord) / 2.0)))
            results.append({
                "vertex_id": f"V{int(self.vertex_ids[index])}",
                "latitude": float(self.latitudes[index]),
                "longitude": float(self.longitudes[index]),
                "distance_km": EARTH_RADIUS_KM * arc,
            })
        return results


def _self_test() -> None:
    """Small, RAM-light test that does not touch the Tamil Nadu graph."""
    points = np.asarray([
        [0.0, 0.0],
        [13.0827, 80.2707],
        [13.085283, 80.284435],
        [19.0760, 72.8777],
    ], dtype=np.float64)
    xyz = _to_unit_sphere(points[:, 0], points[:, 1])
    tree = cKDTree(xyz)
    query_point = _to_unit_sphere(np.asarray([13.0827]), np.asarray([80.2707]))[0]
    distance, index = tree.query(query_point, k=1)
    if int(index) != 1 or float(distance) > 1e-10:
        raise AssertionError("KD-Tree self-test failed")
    # The unit-sphere chord-to-arc conversion should return a near-zero distance.
    arc_km = EARTH_RADIUS_KM * 2.0 * math.asin(min(1.0, float(distance) / 2.0))
    if arc_km > 1e-6:
        raise AssertionError("Distance conversion self-test failed")
    print("KD-Tree self-test passed using four synthetic points.")
    print("The Tamil Nadu graph was not opened or loaded.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Build the index by streaming the graph vertices")
    parser.add_argument("--query", nargs=2, type=float, metavar=("LATITUDE", "LONGITUDE"), help="Query nearest vertex using a built index")
    parser.add_argument("--k", type=int, default=1, help="Number of nearest vertices for --query (default: 1)")
    parser.add_argument("--self-test", action="store_true", help="Run a tiny test without opening the graph")
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH, help="Path to graph JSON")
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR, help="Directory for generated index files")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        return 0
    if args.build:
        build_index(args.graph, args.index_dir)
        return 0
    if args.query:
        index = KDTreeVertexIndex(args.index_dir)
        for result in index.query(args.query[0], args.query[1], k=args.k):
            print(
                f"{result['vertex_id']} | lat={result['latitude']:.6f} "
                f"lon={result['longitude']:.6f} | "
                f"{result['distance_km']:.6f} km"
            )
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
