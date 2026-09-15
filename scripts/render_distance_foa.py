#!/usr/bin/env python3
"""Render fixed-receiver distance sweeps using local SpatialScaper and SoundSpaces.

Only graph-connected, horizontally collinear sample chains are accepted.
The result is the longest supported sampled chain, not a mesh ray-cast claim.
"""
import argparse
import importlib.util
import json
import math
import pickle
from datetime import datetime
from pathlib import Path

import networkx as nx
import numpy as np
import scipy.signal  # SpatialScaper's single-IR branch accesses scipy.signal.
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[2]


def load_spatialize():
    # Load the original implementation without importing Scaper's unrelated
    # SOFA/DCASE dependencies. No changes or copies of vendor code are required.
    path = ROOT / 'repo/data_prep/SpatialScaper-main/spatialscaper/spatialize.py'
    spec = importlib.util.spec_from_file_location('distance_spatialize', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.spatialize


def read_audio(path):
    sr, x = wavfile.read(path)
    if x.dtype.kind == 'u':
        midpoint = 2 ** (x.dtype.itemsize * 8 - 1)
        x = (x.astype(np.float64) - midpoint) / midpoint
    elif x.dtype.kind == 'i':
        x = x.astype(np.float64) / 2 ** (x.dtype.itemsize * 8 - 1)
    else:
        x = x.astype(np.float64)
    if not x.size or not np.isfinite(x).all():
        raise ValueError('Empty or non-finite audio: ' + str(path))
    return sr, x


def select_line(points, graph, rir_dir, receiver=None, tolerance=0.02):
    """Search every sampled ray; require graph edges between consecutive nodes.

    points.txt uses mesh coordinates: first two axes horizontal, third vertical.
    Tiny height variations are retained in the reported Euclidean distances.
    """
    best = None
    nodes = sorted(set(graph.nodes) & set(points))
    for r in nodes:
        if receiver is not None and r != receiver:
            continue
        for end in nodes:
            delta = points[end][:2] - points[r][:2]
            length = np.linalg.norm(delta)
            if length < 0.1:
                continue
            direction = delta / length
            candidates = []
            for s in nodes:
                offset = points[s] - points[r]
                along = float(offset[:2] @ direction)
                cross = np.linalg.norm(offset[:2] - along * direction)
                if (along > 0.01 and along <= length + tolerance
                        and cross <= tolerance and abs(offset[2]) <= tolerance
                        and (rir_dir / f'{r}_{s}.wav').exists()):
                    candidates.append((along, s))
            chain = [r]
            for along, s in sorted(candidates):
                if not graph.has_edge(chain[-1], s):
                    break
                chain.append(s)
            if len(chain) < 2:
                continue
            distance = float(np.linalg.norm(points[chain[-1]][:2] - points[r][:2]))
            key = (distance, len(chain), -r, -chain[-1])
            if best is None or key > best[0]:
                best = (key, chain)
    if best is None:
        raise ValueError('No graph-supported straight sample chain with available RIRs')
    return best[1]


def render_static(spatialize, source, ir, sr):
    # The vendor's single-IR branch truncates to input length. Pad the source
    # to retain exactly the full convolution, including the reverberation tail.
    padded = np.pad(source, (0, len(ir) - 1))
    return spatialize(padded, ir.T[:, None, :], np.array([0.0]), sr=sr)


def choose_positions(positions, answer):
    """Match displayed horizontal distances; never synthesize unavailable RIRs."""
    if not answer.strip() or answer.strip().lower() == 'all':
        return positions.copy()
    tokens = answer.replace('，', ' ').replace(',', ' ').split()
    if not tokens:
        raise ValueError('Enter distances in meters, e.g. 1 3.')
    selected = set()
    for token in tokens:
        try:
            distance = float(token)
        except ValueError:
            raise ValueError(f'Invalid distance: {token}. Enter numbers in meters, e.g. 1 3.') from None
        matches = [i for i, p in enumerate(positions)
                   if math.isfinite(distance) and distance > 0
                   and abs(p['horizontal_distance_m'] - distance) <= 0.000501]
        if len(matches) != 1:
            raise ValueError(f'No unique sample is available at {token} m. Choose from the distances listed above.')
        selected.add(matches[0])
    return [p for i, p in enumerate(positions) if i in selected]


def create_run_directory(parent):
    """Reserve the next run number for today's local date without overwriting."""
    parent.mkdir(parents=True, exist_ok=True)
    prefix = datetime.now().strftime('run-%m%d-')
    numbers = [int(p.name[len(prefix):]) for p in parent.iterdir()
               if p.name.startswith(prefix) and p.name[len(prefix):].isdigit()]
    number = max(numbers, default=0) + 1
    while True:
        output = parent / f'{prefix}{number}'
        try:
            output.mkdir()
            return output
        except FileExistsError:
            number += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, default=ROOT / 'dataset/source-test-0915')
    parser.add_argument('--dataset', type=Path, default=ROOT / 'dataset/soundspaces_1_0')
    parser.add_argument('--output', type=Path,
                        help='Custom output directory; default: outputs/run-MMDD-N relative to the project root')
    parser.add_argument('--scene', action='append', help='Repeat to choose scenes; default: all')
    parser.add_argument('--receiver', type=int, help='Fix a node ID instead of auto selection')
    parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--distances', nargs='+', type=float,
                        help='Horizontal distances in meters; omit to choose interactively')
    parser.add_argument('--all-distances', action='store_true',
                        help='Render every available distance without prompting')
    parser.add_argument('--rir-normalization', choices=['n3d', 'sn3d'], default='n3d',
                        help='Input ACN normalization; local RIR direct-path ratios indicate N3D')
    args = parser.parse_args()
    if args.distances is not None and args.all_distances:
        parser.error('--distances and --all-distances cannot be used together')
    sources = sorted(args.sources.rglob('*.wav'))
    if not sources:
        parser.error('No WAV source files found')
    # Never silently overwrite a previous experiment.
    if args.output is not None and args.output.exists():
        parser.error(f'Output directory already exists. Use --output to specify a new directory: {args.output}')
    metadata = args.dataset / 'data/metadata/mp3d'
    scenes = args.scene or sorted(p.name for p in metadata.iterdir() if p.is_dir())
    report = {'output_format': 'FOA, ACN W,Y,Z,X, SN3D; float32 WAV',
              'input_convention': f'ACN/{args.rir_normalization.upper()}',
              'convention_evidence': 'Inferred from local axial direct-path channel ratios, not file metadata',
              'orientation': 'Native RIR frame retained; no channel-axis rotation',
              'gain_policy': 'One common attenuation for all sources and distances within each scene',
              'delay_policy': 'Original RIR timing retained; no synthetic distance/c delay added',
              'line_scope': 'Longest graph-supported horizontal sampled chain, 2 cm height/line tolerance; no mesh ray casting',
              'scenes': [], 'skipped': []}
    plans = []
    for scene in scenes:
        # Only load the local, previously downloaded trusted metadata pickle.
        with (metadata / scene / 'graph.pkl').open('rb') as f:
            graph = pickle.load(f)
        if graph.number_of_edges() == 0:
            report['skipped'].append({'scene': scene, 'reason': 'Empty connectivity graph'})
            print(f'SKIP {scene}: empty connectivity graph', flush=True)
            continue
        rows = np.loadtxt(metadata / scene / 'points.txt', ndmin=2)
        points = {int(row[0]): row[1:4] for row in rows}
        rir_dir = args.dataset / 'data/ambisonic_rirs/mp3d' / scene / 'irs'
        chain = select_line(points, graph, rir_dir, args.receiver)
        receiver = chain[0]
        entry = {'scene': scene, 'receiver_id': receiver,
                 'receiver_mesh_xyz_m': points[receiver].tolist(), 'positions': [], 'files': []}
        for s in chain[1:]:
            delta = points[s] - points[receiver]
            entry['positions'].append({'source_id': s, 'source_mesh_xyz_m': points[s].tolist(),
                                       'distance_m': float(np.linalg.norm(delta)),
                                       'horizontal_distance_m': float(np.linalg.norm(delta[:2])),
                                       'rir': str(rir_dir / f'{receiver}_{s}.wav')})
        available = entry['positions'].copy()
        entry['available_positions'] = available
        entry['max_horizontal_distance_m'] = max(p['horizontal_distance_m'] for p in available)
        print(f'\nScene: {scene}, fixed receiver: {receiver}', flush=True)
        print(f'Longest horizontal straight-line distance supported by the data: {entry["max_horizontal_distance_m"]:.3f} m'
              ' (not the geometric maximum length of the room)', flush=True)
        print('Available distances (m): ' + ', '.join(
            f'{p["horizontal_distance_m"]:.3f}' for p in available), flush=True)
        if args.distances is not None:
            try:
                entry['positions'] = choose_positions(available, ' '.join(map(str, args.distances)))
            except ValueError as exc:
                parser.error(f'{scene}: {exc}')
        elif not args.all_distances:
            while True:
                try:
                    answer = input('Which distances should be rendered? Enter e.g. 1 3 or 1,2,3; press Enter for all; q to quit: ')
                    if answer.strip().lower() == 'q':
                        print('Cancelled. No output generated.')
                        return
                    entry['positions'] = choose_positions(available, answer)
                    break
                except ValueError as exc:
                    print(exc, flush=True)
                except (EOFError, KeyboardInterrupt):
                    print('\nCancelled. No output generated. For batch runs, use --distances or --all-distances.')
                    return
        print('Selected distances (m): ' + ', '.join(
            f'{p["horizontal_distance_m"]:.3f}' for p in entry['positions']), flush=True)
        report['scenes'].append(entry)
        plans.append(entry)
    if args.output is None:
        args.output = create_run_directory(ROOT / 'outputs')
    else:
        args.output.mkdir(parents=True, exist_ok=False)
    print(f'Output directory: {args.output.resolve()}', flush=True)
    manifest = args.output / 'manifest.json'
    manifest.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    if args.plan_only:
        return
    spatialize = load_spatialize()
    for entry in plans:
        scene_out = args.output / entry['scene']
        scene_out.mkdir()
        peak = 0.0
        for source_path in sources:
            source_sr, source = read_audio(source_path)
            if source.ndim == 2:
                source = source.mean(axis=1)  # one point source from stereo material
            for position in entry['positions']:
                sr, ir = read_audio(position['rir'])
                if ir.ndim != 2 or ir.shape[1] not in (4, 9):
                    raise ValueError('Expected 4/9-channel ACN RIR: ' + position['rir'])
                ir = ir[:, :4].copy()
                if args.rir_normalization == 'n3d':
                    ir[:, 1:] /= math.sqrt(3)
                gcd = math.gcd(source_sr, sr)
                x = scipy.signal.resample_poly(source, sr // gcd, source_sr // gcd)
                rendered = render_static(spatialize, x, ir, sr)
                if not np.isfinite(rendered).all():
                    raise ValueError('Non-finite rendered samples')
                file_peak = float(np.max(np.abs(rendered)))
                peak = max(peak, file_peak)
                relative_source = source_path.relative_to(args.sources)
                out_dir = scene_out / relative_source.parent / relative_source.stem
                out_dir.mkdir(parents=True, exist_ok=True)
                output = out_dir / f'd{position["distance_m"]:.3f}m_r{entry["receiver_id"]}_s{position["source_id"]}_FOA.wav'
                wavfile.write(output, sr, rendered.astype(np.float32))
                entry['files'].append({'path': str(output), 'source': str(source_path),
                                       'source_id': position['source_id'], 'sample_rate': sr,
                                       'frames': len(rendered), 'raw_peak': file_peak})
            print(f'Rendered {entry["scene"]}: {source_path.name}', flush=True)
        gain = min(1.0, 0.95 / peak) if peak else 1.0
        entry['common_gain'] = gain
        for item in entry['files']:
            sr, audio = read_audio(item['path'])
            wavfile.write(item['path'], sr, (audio * gain).astype(np.float32))
            item['output_peak'] = item['raw_peak'] * gain
        manifest.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(f'Done: {manifest}', flush=True)


if __name__ == '__main__':
    main()
