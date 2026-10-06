# Distance Evaluation

Reproducible code and configuration for the 3D-audio distance experiments.
Large datasets and generated audio live in the parent workspace and are not
committed to this repository. The local environment is `repo/.venv`, which is
also ignored by Git.

## Repository layout

```text
docs/                         method and command documentation
scripts/                      project command-line scripts
third_party/spatialscaper/    vendored SpatialScaper source used by rendering
requirements.txt              pinned dependencies for the distance renderer
```

The expected parent workspace contains sibling `datasets/`, `outputs/`,
`docs/`, and `references/` directories. This separation keeps Git history
small while retaining everything needed to describe and rebuild the workflow.

## Setup

From the parent workspace:

```bash
python3.13 -m venv --prompt spatial-audio-distance repo/.venv
source repo/.venv/bin/activate
python -m pip install -r repo/requirements.txt
```

## Commands

```bash
python repo/scripts/preprocess_sources.py
python repo/scripts/render_distance_foa.py
```

See [`docs/render_distance_foa.md`](docs/render_distance_foa.md) for renderer
options, output conventions, and method limitations.

## Data policy

Commit source code, documentation, dependency manifests, configuration, and
small test fixtures. Keep downloaded datasets, copyrighted source audio,
generated outputs, and checkpoints outside Git. Keep caches and the local
virtual environment ignored.

The projects under `third_party/` retain their original licenses and READMEs.
Record the upstream revision whenever either vendored copy is updated.
