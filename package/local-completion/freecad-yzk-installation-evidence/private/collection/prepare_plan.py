"""Root-only new private explicit installation file plan; no product execution."""
import sys
sys.dont_write_bytecode = True

import argparse
import json
from pathlib import Path

from evidence_packet import PRIVATE, Packet, descriptor, digest, json_bytes, load, read_regular, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not sys.flags.optimize, 'Use an unoptimized interpreter')
    audit_path = PRIVATE / 'final-audit.json'
    audit_bytes = read_regular(audit_path)
    require(digest(audit_bytes) == args.audit_sha256, 'Exact completed audit SHA required')
    audit = json.loads(audit_bytes)
    require(audit['schema'] == 'FreeCAD-yzk-final-installation-filesystem-audit-v1'
            and audit['passed'] is True, 'Completed final audit required')
    files = list(audit['publishable_inputs'])
    files.append({'scope': 'private', 'path': 'final-audit.json', 'destination': 'private/final-audit.json',
                  'sha256': args.audit_sha256, 'kind': 'receipt',
                  'classification': 'Completed filesystem-only audit; no new native/signature execution'})
    require(len({(row['scope'], row['path']) for row in files}) == len(files), 'Duplicate explicit source')
    packet = Packet()
    for row in files:
        packet.add(row)
    packet.unchanged()
    result = {'schema': 'FreeCAD-yzk-installed-approved-file-plan-v1',
              'audit': {'path': str(audit_path), 'sha256': args.audit_sha256, 'bytes': len(audit_bytes)},
              'files': sorted(files, key=lambda row: (row['scope'], row['path'])),
              'explicit_inputs': len(files), 'root_review_required_before_publication': True,
              'native_app_build_test_sign_installation_executed': False,
              'large_FCStd_FRD_and_private_inventory_bodies_are_not_payloads': True}
    target = args.output.absolute()
    require(target.parent == PRIVATE / 'collection' and not target.exists() and not target.is_symlink(),
            'New private plan only')
    with target.open('xb') as stream:
        stream.write(json_bytes(result))
    print(json_bytes({'passed': True, 'plan': descriptor(target), 'explicit_inputs': len(files),
                      'product_or_repository_writes': 0}).decode(), end='')


if __name__ == '__main__':
    main()
