import argparse
from pathlib import Path


IDENTIFIED_FILENAMES = [
    "SSIS-001.mp4",
    "ssis002 sample.mkv",
    "IPZZ_123.avi",
    "MIDV 888.wmv",
    "CAWD456.mov",
    "ABW-100.ts",
    "JUQ_321.m2ts",
    "SONE777.mp4",
    "MIAA-888.mkv",
    "FSDSS_999.avi",
    "DASS 123.wmv",
    "PRED456.mov",
    "MEYD-789.ts",
    "STARS_555.m2ts",
    "JUL-404.mp4",
    "WANZ999.mkv",
]

UNIDENTIFIED_FILENAMES = [
    "family-holiday.mp4",
    "movie_final.mkv",
    "sample-video.avi",
    "2025-vacation.mov",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create zero-byte demo media files without overwriting existing files.")
    parser.add_argument("--output", default="demo-media", help="Destination directory (default: demo-media)")
    parser.add_argument("--dry-run", action="store_true", help="Print filenames without creating them")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    filenames = IDENTIFIED_FILENAMES + UNIDENTIFIED_FILENAMES
    if not args.dry_run:
        output.mkdir(parents=True, exist_ok=True)
        if not output.is_dir():
            raise SystemExit(f"Output is not a directory: {output}")

    created = 0
    existing = 0
    for filename in filenames:
        destination = output / filename
        if args.dry_run:
            print(filename)
            continue
        try:
            with destination.open("xb"):
                pass
            created += 1
        except FileExistsError:
            existing += 1

    if args.dry_run:
        print(f"Dry run: {len(filenames)} zero-byte files would be created in {output}")
    else:
        print(f"Demo directory: {output}")
        print(f"Created: {created}; already existed and left unchanged: {existing}")
    print("Expected result: 20 videos, 16 identified, 4 unidentified, recognition rate 80%")


if __name__ == "__main__":
    main()
