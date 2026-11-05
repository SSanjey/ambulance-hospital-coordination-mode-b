"""Safely preview the adjacency section of the Tamil Nadu graph JSON.

Reads the graph in fixed-size binary chunks and prints a small sample around
its top-level ``adjacency`` key. It does not parse or load the full graph and
never writes to the graph file.

Run from the project root:
    python routing\\mode_b\\inspect_adjacency.py
"""
from pathlib import Path

GRAPH = Path(__file__).resolve().parents[1] / "tamil_nadu_graph.json"
NEEDLE = b'"adjacency"'
CHUNK_SIZE = 1024 * 1024
SAMPLE_BYTES = 2200
OVERLAP = len(NEEDLE) - 1


def main() -> int:
    if not GRAPH.is_file():
        print(f"ERROR: Graph not found: {GRAPH}")
        return 1

    print(f"Scanning graph in {CHUNK_SIZE:,}-byte chunks: {GRAPH}")
    scanned = 0
    tail = b""
    with GRAPH.open("rb") as stream:
        while True:
            chunk = stream.read(CHUNK_SIZE)
            if not chunk:
                break
            scanned += len(chunk)
            combined = tail + chunk
            position = combined.find(NEEDLE)
            if position >= 0:
                sample_start = position
                sample = combined[sample_start:sample_start + SAMPLE_BYTES]
                while len(sample) < SAMPLE_BYTES:
                    more = stream.read(SAMPLE_BYTES - len(sample))
                    if not more:
                        break
                    sample += more
                print(f"Found top-level adjacency key after scanning about {scanned:,} bytes.")
                print("--- ADJACENCY SAMPLE (read-only preview) ---")
                print(sample.decode("utf-8", errors="replace"))
                print("--- END SAMPLE ---")
                print("No graph data was changed, and the full graph was not loaded.")
                return 0
            tail = combined[-OVERLAP:] if OVERLAP else b""

    print('ERROR: Could not find the key "adjacency" in the graph file.')
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
