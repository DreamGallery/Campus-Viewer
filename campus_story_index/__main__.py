import argparse
import json
import sys
import csv
import yaml

from .builder import CatalogBuilder
from .io import atomic_write


def main():
    parser = argparse.ArgumentParser(description='Build the offline, unified Gakumas story catalog.')
    parser.add_argument('--masterdata', required=True, help='Local gakumasu-diff directory')
    parser.add_argument('--stories', required=True, help='Campus-Story directory containing CSV/')
    parser.add_argument('--output', default='generated/story-index.json', help='Atomic JSON output file')
    parser.add_argument('--strict', action='store_true', help='Fail on dangling relationships or unknown source adapters')
    args = parser.parse_args()
    try:
        catalog = CatalogBuilder(args.masterdata, args.stories).build()
        blocking = {'dangling_story_reference', 'missing_group', 'unmapped_script_source', 'unstable_source_key'}
        if args.strict and any(d['code'] in blocking for d in catalog['diagnostics']):
            raise ValueError('Strict validation failed: ' + json.dumps(catalog['stats']['diagnostic_counts']))
        atomic_write(args.output, catalog)
    except (ValueError, OSError, csv.Error, yaml.YAMLError) as exc:
        print(f'Index build failed: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({'output': args.output, **catalog['stats']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
