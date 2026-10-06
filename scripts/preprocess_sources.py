#!/usr/bin/env python3
"""Standardize a folder of dry-source WAV files for spatial rendering."""

import argparse
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
DATASET_ROOT = WORKSPACE_ROOT / "datasets"
OUTPUT_SUFFIX = "-preprocessed"
TARGET_SAMPLE_RATE = 44100
TARGET_RMS_DBFS = -20.0


def calculate_rms(audio):
    """Calculate the RMS amplitude of an audio signal."""
    return np.sqrt(np.mean(audio ** 2))


def rms_to_dbfs(rms):
    """Convert linear RMS amplitude to dBFS."""
    if rms <= 0:
        return -np.inf
    return 20 * np.log10(rms)


def normalize_rms(audio, target_dbfs):
    """Normalize a signal to a target RMS level."""
    current_rms = calculate_rms(audio)
    if current_rms <= 0:
        return None
    target_rms = 10 ** (target_dbfs / 20)
    return audio * (target_rms / current_rms)


def resample_audio(audio, source_rate, target_rate):
    """Resample along the time axis with a polyphase anti-aliasing filter."""
    divisor = gcd(source_rate, target_rate)
    up = target_rate // divisor
    down = source_rate // divisor
    return resample_poly(audio, up, down, axis=0).astype(np.float32)


def find_wav_files(folder):
    """Return WAV files recursively, accepting upper- or lower-case suffixes."""
    return sorted(
        (path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() == ".wav"),
        key=lambda path: str(path.relative_to(folder)).lower(),
    )


def discover_dataset_folders(dataset_root):
    """List first-level dataset folders containing at least one WAV file."""
    folders = []
    for path in sorted(
        (item for item in dataset_root.iterdir() if item.is_dir()),
        key=lambda item: item.name.lower(),
    ):
        # Do not offer an earlier preprocessing output as a new source by default.
        if path.name.endswith(OUTPUT_SUFFIX):
            continue
        wav_count = len(find_wav_files(path))
        if wav_count:
            folders.append((path, wav_count))
    return folders


def choose_dataset_folder(folders, answer):
    """Choose a displayed folder by number or exact folder name."""
    value = answer.strip()
    if not value:
        raise ValueError("Enter a folder number or name.")
    if value.isdigit():
        index = int(value) - 1
        if 0 <= index < len(folders):
            return folders[index][0]
    matches = [path for path, _ in folders if path.name == value]
    if len(matches) == 1:
        return matches[0]
    raise ValueError("No such folder. Enter one of the numbers or exact names listed above.")


def prompt_for_input_folder(dataset_root):
    """Interactively select one source folder under datasets/."""
    folders = discover_dataset_folders(dataset_root)
    if not folders:
        raise ValueError(f"No folders containing WAV files were found in {dataset_root}.")

    print(f"Available source folders ({dataset_root}):", flush=True)
    for index, (path, wav_count) in enumerate(folders, start=1):
        print(f"  {index}. {path.name} ({wav_count} WAV files)", flush=True)

    while True:
        try:
            answer = input("Select a folder to preprocess (number or name; q to quit): ")
            if answer.strip().lower() == "q":
                return None
            return choose_dataset_folder(folders, answer)
        except ValueError as exc:
            print(exc, flush=True)
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled. No output was generated.")
            return None


def resolve_input_folder(value, dataset_root):
    """Resolve --input as either a dataset child name or a filesystem path."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        dataset_child = dataset_root / path
        path = dataset_child if dataset_child.is_dir() else path.resolve()
    return path.resolve()


def process_folder(input_dir, output_dir):
    """Process every WAV below input_dir and preserve relative directories."""
    wav_files = find_wav_files(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nInput folder:  {input_dir}")
    print(f"Output folder: {output_dir}")
    print(f"Found {len(wav_files)} WAV files.\n")

    processed_count = 0
    skipped_count = 0
    warning_count = 0

    for path in wav_files:
        relative_path = path.relative_to(input_dir)
        print("=" * 60)
        print(f"Processing: {relative_path}")

        try:
            audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
            if audio.size == 0:
                print("SKIPPED: Empty audio file.")
                skipped_count += 1
                continue
            if not np.all(np.isfinite(audio)):
                print("SKIPPED: Audio contains invalid numerical values.")
                skipped_count += 1
                continue

            original_rms = calculate_rms(audio)
            if original_rms <= 0:
                print("SKIPPED: Silent audio file.")
                skipped_count += 1
                continue

            print("Validity:          OK")
            print(f"Original SR:       {sample_rate} Hz")
            print(f"Original channels: {audio.shape[1]}")
            print(f"Original RMS:      {rms_to_dbfs(original_rms):.2f} dBFS")

            if audio.shape[1] == 2:
                audio = np.mean(audio, axis=1, keepdims=True)
                print("Channels:          Stereo -> Mono")
            elif audio.shape[1] == 1:
                print("Channels:          Mono -> Mono")
            else:
                print(f"SKIPPED: Unexpected number of channels ({audio.shape[1]}).")
                skipped_count += 1
                continue

            if sample_rate != TARGET_SAMPLE_RATE:
                original_sample_rate = sample_rate
                audio = resample_audio(audio, sample_rate, TARGET_SAMPLE_RATE)
                sample_rate = TARGET_SAMPLE_RATE
                print(
                    f"Sample rate:       {original_sample_rate} Hz -> "
                    f"{TARGET_SAMPLE_RATE} Hz"
                )
            else:
                print(f"Sample rate:       {TARGET_SAMPLE_RATE} Hz (unchanged)")

            rms_before_normalization = calculate_rms(audio)
            print(f"Mono RMS before:    {rms_to_dbfs(rms_before_normalization):.2f} dBFS")
            audio = normalize_rms(audio, TARGET_RMS_DBFS)
            if audio is None:
                print("SKIPPED: RMS normalization failed.")
                skipped_count += 1
                continue
            print(f"Normalized RMS:     {rms_to_dbfs(calculate_rms(audio)):.2f} dBFS")

            peak = np.max(np.abs(audio))
            peak_dbfs = 20 * np.log10(peak) if peak > 0 else -np.inf
            print(f"Peak level:         {peak_dbfs:.2f} dBFS")
            if peak > 1.0:
                print(
                    "WARNING: Peak amplitude exceeds 0 dBFS. "
                    "The signal may clip when saved as PCM_16."
                )
                warning_count += 1

            output_path = output_dir / relative_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(output_path, audio, TARGET_SAMPLE_RATE, subtype="PCM_16")
            print(f"Saved:              {output_path}")
            processed_count += 1

        except Exception as exc:
            print(f"ERROR: Could not process {relative_path}")
            print(f"Reason: {exc}")
            skipped_count += 1

    print("\n" + "=" * 60)
    print("Preprocessing complete.\n")
    print(f"Total files:        {len(wav_files)}")
    print(f"Processed files:    {processed_count}")
    print(f"Skipped files:      {skipped_count}")
    print(f"Peak warnings:      {warning_count}")
    print(f"Output folder:      {output_dir}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        help="input folder path or folder name under datasets/; omit for interactive selection",
    )
    args = parser.parse_args()

    if not DATASET_ROOT.is_dir():
        parser.error(f"Dataset folder does not exist: {DATASET_ROOT}")

    if args.input:
        input_dir = resolve_input_folder(args.input, DATASET_ROOT)
    else:
        try:
            input_dir = prompt_for_input_folder(DATASET_ROOT)
        except ValueError as exc:
            parser.error(str(exc))
        if input_dir is None:
            print("Cancelled. No output was generated.")
            return

    if not input_dir.is_dir():
        parser.error(f"Input folder does not exist: {input_dir}")
    if not find_wav_files(input_dir):
        parser.error(f"No WAV files found in: {input_dir}")

    output_dir = input_dir.with_name(input_dir.name + OUTPUT_SUFFIX)
    if output_dir.exists() and any(output_dir.iterdir()):
        parser.error(
            f"Output folder already exists: {output_dir}\n"
            "Rename or move it before running again to avoid overwriting existing results."
        )

    print(f"Selected: {input_dir.name}", flush=True)
    print(f"Output:   {output_dir.name}", flush=True)
    process_folder(input_dir, output_dir)


if __name__ == "__main__":
    main()
