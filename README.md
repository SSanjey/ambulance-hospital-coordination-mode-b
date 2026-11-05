# Ambulance and Hospital Coordination System — Mode B

## Overview
Mode B is a separate implementation of the ambulance and hospital coordination system. It uses spatial indexing and road-network routing to support emergency ambulance and hospital selection in Tamil Nadu.

## Main Components
- Python HTTP server and browser dashboard.
- KD-tree spatial indexing for candidate generation and filtering.
- Weighted candidate evaluation for dispatch selection.
- Static A*, Dynamic A*, and Time-aware A* routing options.
- Precomputed compact road-graph data and spatial-index files.

## Run
From the repository root:

    python app/mode_b/server.py

The application is configured for:

    http://127.0.0.1:8765

## Road Network
The application uses a Tamil Nadu road-network graph derived from OpenStreetMap data. The graph is tracked using Git LFS. Precomputed compact graph and KD-tree data files are also included.

After cloning:

    git lfs install
    git lfs pull

See DATA_SOURCES.md for attribution and data licensing information.

## Data Availability
Operational ambulance records and the locally assembled healthcare-facility CSV are excluded pending privacy and redistribution-permission review. Authorized local data may be required for the complete workflow.

## Limitations
This is an academic project, not a certified emergency-response service.

## Author
Sanjey S — https://github.com/SSanjey

## Citation
See CITATION.cff.

## Software License
No software license is provided for the application source code. Public visibility does not grant reuse or redistribution permission.
