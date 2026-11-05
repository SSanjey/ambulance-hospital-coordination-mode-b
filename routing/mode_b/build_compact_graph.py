"""Build a compact CSR road graph for Mode B without loading the full JSON graph.

Run from the project root:
    python routing\\mode_b\\build_compact_graph.py --self-test
    python routing\\mode_b\\build_compact_graph.py --build

Outputs are written under routing/mode_b/graph_data/. The source graph is read-only.
The existing Mode A routing scripts are not imported or modified.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import tempfile
from pathlib import Path
from typing import Any, Iterator

import numpy as np

try:
    from kdtree_index import _JSONStream
except ImportError:  # supports module-style import from project root
    from routing.mode_b.kdtree_index import _JSONStream  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GRAPH_FILE = PROJECT_ROOT / "routing" / "tamil_nadu_graph.json"
INDEX_DIR = PROJECT_ROOT / "routing" / "mode_b" / "kdtree_data"
OUTPUT_DIR = PROJECT_ROOT / "routing" / "mode_b" / "graph_data"
ID_PATTERN = re.compile(r"^V([0-9]+)$")

# Compact uint8 codes aligned edge-for-edge with edge_targets.npy and
# edge_distances_km.npy. Unknown/missing classes use the generic "road" code.
ROAD_CLASS_TO_CODE = {
    "road": 0,
    "motorway": 1,
    "motorway_link": 2,
    "trunk": 3,
    "trunk_link": 4,
    "primary": 5,
    "primary_link": 6,
    "secondary": 7,
    "secondary_link": 8,
    "tertiary": 9,
    "tertiary_link": 10,
    "unclassified": 11,
    "residential": 12,
    "living_street": 13,
    "service": 14,
}

CHUNK_SIZE = 1024 * 1024
LOG_EVERY = 100_000


def _find_adjacency_value_offset(graph_path: Path) -> int:
    """Return a byte offset immediately after the opening brace of adjacency."""
    needle = b'"adjacency"'
    overlap = len(needle) - 1
    total_read = 0
    tail = b""
    with graph_path.open("rb") as stream:
        while True:
            chunk = stream.read(CHUNK_SIZE)
            if not chunk:
                break
            combined = tail + chunk
            found = combined.find(needle)
            if found >= 0:
                absolute = total_read - len(tail) + found
                stream.seek(absolute + len(needle))
                # Skip JSON whitespace, colon and whitespace before '{'.
                while True:
                    ch = stream.read(1)
                    if not ch:
                        raise ValueError("Unexpected EOF after adjacency key")
                    if ch not in b" \t\r\n":
                        if ch != b":":
                            raise ValueError("Malformed JSON after adjacency key")
                        break
                while True:
                    ch = stream.read(1)
                    if not ch:
                        raise ValueError("Unexpected EOF before adjacency object")
                    if ch not in b" \t\r\n":
                        if ch != b"{":
                            raise ValueError("The top-level adjacency value is not an object")
                        return stream.tell()
            total_read += len(chunk)
            tail = combined[-overlap:] if overlap else b""
    raise KeyError("Top-level 'adjacency' key not found in graph JSON")


def iter_adjacency(graph_path: Path) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    """Yield source numeric ID and one source's outgoing edge list at a time."""
    offset = _find_adjacency_value_offset(graph_path)
    # The input graph is ASCII JSON; offset discovered in binary mode points to
    # a character boundary. _JSONStream decodes one small edge list at a time.
    with graph_path.open("r", encoding="utf-8") as file_obj:
        file_obj.seek(offset)
        stream = _JSONStream(file_obj)
        while True:
            token = stream.peek()
            if token == "}":
                stream.expect("}")
                return
            source_value = stream.read_value()
            if not isinstance(source_value, str):
                raise ValueError(
                    f"Expected adjacency source ID string, got {type(source_value).__name__}"
                )
            match = ID_PATTERN.fullmatch(source_value)
            if not match:
                raise ValueError(f"Unsupported source node ID {source_value!r}")
            source_id = int(match.group(1))
            stream.expect(":")
            edges = stream.read_value()
            if not isinstance(edges, list):
                raise ValueError(f"Adjacency for {source_value} must be a list")
            yield source_id, edges
            token = stream.peek()
            if token == ",":
                stream.expect(",")
            elif token == "}":
                stream.expect("}")
                return
            else:
                raise ValueError(f"Unexpected token {token!r} after adjacency for {source_value}")


def _id_to_index(value: Any, context: str) -> int:
    if not isinstance(value, str):
        raise ValueError(f"{context}: expected node ID string, got {type(value).__name__}")
    match = ID_PATTERN.fullmatch(value)
    if not match:
        raise ValueError(f"{context}: unsupported node ID {value!r}")
    numeric = int(match.group(1))
    if numeric < 1:
        raise ValueError(f"{context}: node ID must be >= V1, got {value!r}")
    return numeric - 1


def _check_required_index_files(index_dir: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    names = ("vertex_ids.npy", "latitudes.npy", "longitudes.npy")
    missing = [name for name in names if not (index_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing KD-tree coordinate files: " + ", ".join(missing)
            + ". Build the index first with kdtree_index.py --build."
        )
    ids = np.load(index_dir / "vertex_ids.npy", mmap_mode="r")
    latitudes = np.load(index_dir / "latitudes.npy", mmap_mode="r")
    longitudes = np.load(index_dir / "longitudes.npy", mmap_mode="r")
    if not (len(ids) == len(latitudes) == len(longitudes)):
        raise ValueError("Vertex ID and coordinate index lengths do not match")
    if len(ids) == 0:
        raise ValueError("Coordinate index is empty")
    # The project graph was previously verified to have contiguous IDs. Check
    # range here as an additional guard without creating a large sort array.
    n = len(ids)
    if int(ids.min()) != 1 or int(ids.max()) != n:
        raise ValueError("Expected contiguous numeric vertex IDs from V1 through Vn")
    return ids, latitudes, longitudes


def _build_coordinates_by_id(index_dir: Path, out_dir: Path, n: int) -> None:
    """Write coordinate arrays indexed directly by (numeric_vertex_id - 1)."""
    ids = np.load(index_dir / "vertex_ids.npy", mmap_mode="r")
    lats = np.load(index_dir / "latitudes.npy", mmap_mode="r")
    lons = np.load(index_dir / "longitudes.npy", mmap_mode="r")
    lat_out = np.lib.format.open_memmap(
        out_dir / "latitudes_by_id.npy", mode="w+", dtype=np.float32, shape=(n,)
    )
    lon_out = np.lib.format.open_memmap(
        out_dir / "longitudes_by_id.npy", mode="w+", dtype=np.float32, shape=(n,)
    )
    step = 200_000
    for start in range(0, n, step):
        end = min(n, start + step)
        positions = np.asarray(ids[start:end], dtype=np.int64) - 1
        lat_out[positions] = lats[start:end]
        lon_out[positions] = lons[start:end]
    lat_out.flush()
    lon_out.flush()
    del ids, lats, lons, lat_out, lon_out


def build_compact_graph(
    graph_path: Path = GRAPH_FILE,
    index_dir: Path = INDEX_DIR,
    out_dir: Path = OUTPUT_DIR,
) -> dict[str, int]:
    """Build CSR arrays and aligned highway codes using two streaming passes."""
    if not graph_path.is_file():
        raise FileNotFoundError(f"Road graph file not found: {graph_path}")
    ids, lats, lons = _check_required_index_files(index_dir)
    n = len(ids)
    del ids, lats, lons
    out_dir.mkdir(parents=True, exist_ok=True)

    degree_path = out_dir / "_build_outdegree.npy"
    seen_path = out_dir / "_build_seen.npy"
    outdegree = np.lib.format.open_memmap(degree_path, mode="w+", dtype=np.uint32, shape=(n,))
    seen = np.lib.format.open_memmap(seen_path, mode="w+", dtype=np.uint8, shape=(n,))
    outdegree[:] = 0
    seen[:] = 0
    outdegree.flush()
    seen.flush()

    print(f"Pass 1/2: counting directed edges from {graph_path}")
    source_count = 0
    edge_count = 0
    for source_id, edges in iter_adjacency(graph_path):
        if not 1 <= source_id <= n:
            raise ValueError(f"Source node V{source_id} is outside the indexed vertex range")
        source_index = source_id - 1
        if seen[source_index]:
            raise ValueError(f"Duplicate adjacency source key V{source_id}")
        seen[source_index] = 1
        outdegree[source_index] = len(edges)
        source_count += 1
        edge_count += len(edges)
        if source_count % LOG_EVERY == 0:
            print(f"  Counted {source_count:,} source nodes and {edge_count:,} edges...")
    outdegree.flush()
    seen.flush()
    if source_count == 0 or edge_count == 0:
        raise ValueError("No adjacency records or edges were found")
    print(f"  Pass 1 complete: {source_count:,} source nodes, {edge_count:,} directed edges")

    indptr_path = out_dir / "indptr.npy"
    targets_path = out_dir / "edge_targets.npy"
    distances_path = out_dir / "edge_distances_km.npy"
    indptr = np.lib.format.open_memmap(indptr_path, mode="w+", dtype=np.int64, shape=(n + 1,))
    indptr[0] = 0
    np.cumsum(outdegree, dtype=np.int64, out=indptr[1:])
    indptr.flush()
    computed_edges = int(indptr[-1])
    if computed_edges != edge_count:
        raise RuntimeError(
            f"Edge count mismatch: counted {edge_count}, CSR prefix total is {computed_edges}"
        )

    edge_targets = np.lib.format.open_memmap(
        targets_path,
        mode="w+",
        dtype=np.int32,
        shape=(edge_count,),
    )
    edge_distances = np.lib.format.open_memmap(
        distances_path,
        mode="w+",
        dtype=np.float32,
        shape=(edge_count,),
    )
    highways_path = out_dir / "edge_highway_codes.npy"
    edge_highways = np.lib.format.open_memmap(
        highways_path,
        mode="w+",
        dtype=np.uint8,
        shape=(edge_count,),
    )
    # A 14 MB int64 copy is smaller than a Python dict for 1.74M nodes.
    cursor = np.array(indptr[:-1], dtype=np.int64, copy=True)

    print("Pass 2/2: filling compact CSR edge arrays")
    filled_sources = 0
    filled_edges = 0
    for source_id, edges in iter_adjacency(graph_path):
        source_index = source_id - 1
        start = int(cursor[source_index])
        count = len(edges)
        end = start + count
        if end > edge_count:
            raise RuntimeError(f"CSR write range exceeded for source V{source_id}")

        target_values = np.fromiter(
            (_id_to_index(edge.get("to"), f"edge from V{source_id}") for edge in edges),
            dtype=np.int32,
            count=count,
        )
        distance_values = np.fromiter(
            (float(edge.get("distance_km")) for edge in edges),
            dtype=np.float32,
            count=count,
        )
        highway_values = np.fromiter(
            (
                ROAD_CLASS_TO_CODE.get(
                    str(edge.get("highway", "road")).strip().lower(),
                    0,
                )
                for edge in edges
            ),
            dtype=np.uint8,
            count=count,
        )

        if count:
            if int(target_values.min()) < 0 or int(target_values.max()) >= n:
                raise ValueError(f"An edge from V{source_id} points outside the indexed vertex range")
            if not np.all(np.isfinite(distance_values)) or np.any(distance_values <= 0):
                raise ValueError(f"Invalid distance value in adjacency for V{source_id}")
            edge_targets[start:end] = target_values
            edge_distances[start:end] = distance_values
            edge_highways[start:end] = highway_values

        # Advance the CSR row cursor after writing all arrays for this source.
        cursor[source_index] = end
        filled_sources += 1
        filled_edges += count
        if filled_sources % LOG_EVERY == 0:
            print(f"  Filled {filled_sources:,} source nodes and {filled_edges:,} edges...")

    if filled_sources != source_count or filled_edges != edge_count:
        raise RuntimeError(
            f"Pass mismatch: first pass {source_count:,}/{edge_count:,}, "
            f"second pass {filled_sources:,}/{filled_edges:,}"
        )
    if not np.array_equal(cursor, indptr[1:]):
        raise RuntimeError("CSR cursor validation failed; one or more adjacency rows were not filled correctly")

    edge_targets.flush()
    edge_distances.flush()
    edge_highways.flush()
    del outdegree, seen, indptr, edge_targets, edge_distances, edge_highways, cursor
    for temporary in (degree_path, seen_path):
        try:
            temporary.unlink()
        except OSError:
            pass

    print("Writing coordinates indexed by numeric vertex ID...")
    _build_coordinates_by_id(index_dir, out_dir, n)

    stat = graph_path.stat()
    metadata = {
        "format": "CSR (Compressed Sparse Row)",
        "vertex_count": n,
        "adjacency_source_count": source_count,
        "directed_edge_count": edge_count,
        "node_ids": "Vn maps to zero-based index n-1",
        "edge_target_dtype": "int32 zero-based vertex indices",
        "edge_distance_dtype": "float32 kilometres",
        "edge_highway_codes_file": "edge_highway_codes.npy",
        "edge_highway_code_dtype": "uint8",
        "highway_code_to_name": {
            str(code): name for name, code in ROAD_CLASS_TO_CODE.items()
        },
        "indptr_dtype": "int64",
        "graph_file_size_bytes": stat.st_size,
        "graph_file_mtime_ns": stat.st_mtime_ns,
        "graph_source": str(graph_path),
    }
    metadata_path = out_dir / "graph_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print("\nCOMPACT GRAPH BUILD COMPLETE")
    print(f"Vertices indexed       : {n:,}")
    print(f"Adjacency source nodes : {source_count:,}")
    print(f"Directed edges         : {edge_count:,}")
    print(f"Output directory       : {out_dir}")
    print("Road-category codes    : edge_highway_codes.npy")
    print("Mode A source files were not modified.")
    return {
        "vertex_count": n,
        "adjacency_source_count": source_count,
        "directed_edge_count": edge_count,
    }


def _self_test() -> None:
    """Test streaming parser plus compact builder on tiny synthetic data only."""
    parser_graph_text = (
        '{"metadata":{"region":"test"},"vertices":{"V1":{"latitude":0,"longitude":0},'
        '"V2":{"latitude":0,"longitude":1},"V3":{"latitude":1,"longitude":1}},'
        '"adjacency":{"V3":[{"to":"V2","distance_km":1.2}],'
        '"V1":[{"to":"V2","distance_km":3.4},{"to":"V3","distance_km":5.6}]}}'
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        parser_path = root / "parser_tiny.json"
        parser_path.write_text(parser_graph_text, encoding="utf-8")
        rows = list(iter_adjacency(parser_path))
        assert rows == [
            (3, [{"to": "V2", "distance_km": 1.2}]),
            (1, [
                {"to": "V2", "distance_km": 3.4},
                {"to": "V3", "distance_km": 5.6},
            ]),
        ], rows

        # Build a separate 3-vertex graph to verify array alignment and code map.
        graph_path = root / "tiny_build_graph.json"
        graph_text = (
            '{"metadata":{"region":"synthetic"},'
            '"vertices":{"V1":{"latitude":0,"longitude":0},'
            '"V2":{"latitude":0,"longitude":1},"V3":{"latitude":1,"longitude":1}},'
            '"adjacency":{' 
            '"V1":[{"to":"V2","distance_km":1.0,"highway":"primary"},'
            '{"to":"V3","distance_km":2.5,"highway":"service"}],'
            '"V2":[{"to":"V3","distance_km":1.2,"highway":"residential"}],'
            '"V3":[]}}'
        )
        graph_path.write_text(graph_text, encoding="utf-8")
        index_dir = root / "index"
        out_dir = root / "compact"
        index_dir.mkdir()
        np.save(index_dir / "vertex_ids.npy", np.array([1, 2, 3], dtype=np.int32))
        np.save(index_dir / "latitudes.npy", np.array([0.0, 0.0, 1.0], dtype=np.float32))
        np.save(index_dir / "longitudes.npy", np.array([0.0, 1.0, 1.0], dtype=np.float32))

        stats = build_compact_graph(graph_path, index_dir, out_dir)
        assert stats == {
            "vertex_count": 3,
            "adjacency_source_count": 3,
            "directed_edge_count": 3,
        }, stats
        targets = np.load(out_dir / "edge_targets.npy")
        distances = np.load(out_dir / "edge_distances_km.npy")
        highways = np.load(out_dir / "edge_highway_codes.npy")
        metadata = json.loads((out_dir / "graph_metadata.json").read_text(encoding="utf-8"))
        assert targets.tolist() == [1, 2, 2], targets.tolist()
        assert np.allclose(distances, [1.0, 2.5, 1.2]), distances.tolist()
        assert highways.tolist() == [5, 14, 12], highways.tolist()
        assert metadata["highway_code_to_name"]["5"] == "primary"
        assert metadata["edge_highway_code_dtype"] == "uint8"

    print("Compact graph parser self-test passed on a three-vertex synthetic graph.")
    print("Compact graph build self-test passed: highway codes align with CSR edges.")
    print("The Tamil Nadu graph was not opened or loaded; no project graph files were modified.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true", help="Build CSR files by streaming the source graph twice")
    group.add_argument("--self-test", action="store_true", help="Test parser and compact builder on a tiny synthetic graph")
    parser.add_argument("--graph", type=Path, default=GRAPH_FILE)
    parser.add_argument("--index-dir", type=Path, default=INDEX_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    build_compact_graph(args.graph, args.index_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
