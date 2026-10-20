"""Root-only reviewed-plan check/publication; filesystem reads, no native calls.

Check-only writes0. The completed audit is recomputed by filesystem/hash/JSON
checks before either mode; successful source-only legacy runs are inherited by
candidate parity and are not represented as fresh installed executions.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import json
from pathlib import Path

from audit_installation_v2 import Audit
from evidence_packet import PRIVATE, REPOSITORY, Packet, descriptor, digest, json_bytes, load, read_regular, require


DESTINATION = REPOSITORY / 'package/local-completion/freecad-yzk-installation-evidence'
SUMMARY = REPOSITORY / 'package/local-completion/freecad-yzk-installation.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    require(not sys.flags.optimize, 'Use an unoptimized interpreter')
    plan_path = args.plan.absolute()
    plan_bytes = read_regular(plan_path)
    require(plan_path.parent == PRIVATE / 'collection'
            and digest(plan_bytes) == args.plan_sha256, 'Exact root-reviewed private plan required')
    plan = json.loads(plan_bytes)
    require(plan['schema'] == 'FreeCAD-yzk-installed-approved-file-plan-v1', 'Wrong explicit plan schema')
    audit_path = PRIVATE / 'final-audit.json'
    audit_bytes = read_regular(audit_path)
    require(plan['audit'] == {'path': str(audit_path), 'sha256': digest(audit_bytes), 'bytes': len(audit_bytes)},
            'Final audit descriptor differs')
    saved = json.loads(audit_bytes)
    fresh = Audit().run([Path(path) for path in saved['review_files']])
    require(fresh == saved, 'Final installed state or completed evidence changed after audit')
    expected = list(saved['publishable_inputs']) + [{
        'scope': 'private', 'path': 'final-audit.json', 'destination': 'private/final-audit.json',
        'sha256': descriptor(audit_path)['sha256'], 'kind': 'receipt',
        'classification': 'Completed filesystem-only audit; no new native/signature execution'}]
    require(plan['files'] == sorted(expected, key=lambda row: (row['scope'], row['path']))
            and plan['explicit_inputs'] == len(expected), 'Plan is not the exact audited input set')
    packet = Packet()
    for entry in plan['files']:
        packet.add(entry)
    packet.add({'scope': 'private', 'path': str(plan_path.relative_to(PRIVATE)),
                'destination': 'approved-plan.json', 'sha256': args.plan_sha256, 'kind': 'receipt',
                'classification': 'Exact separately root-reviewed publication file plan'})
    index = {'schema': 'FreeCAD-yzk-installation-evidence-index-v1',
             'files': sorted(packet.records, key=lambda row: row['file']),
             'approved_plan': descriptor(plan_path), 'explicit_input_count': len(expected),
             'indexed_file_count': len(packet.records),
             'omission_disclosure': 'FCStd/FRD/other large geometry artifacts, raw app/profile inventories, caches, credentials, runtime binaries and native vendor trees are not payloads. The declared generic Mesh.inp native input geometry IS retained. Exact omitted generic-original descriptors remain in the selection custody and final audit.'}
    summary = {'schema': 'FreeCAD-yzk-installation-v1', 'passed': True,
        'source_commit': saved['source_commit'], 'compiled_revision': saved['compiled_revision'],
        'application': saved['application'], 'rollback_backup': saved['backup'],
        'native_sha256': saved['native_sha256'], 'qualification': saved['results'],
        'custody': {key: saved[key] for key in (
            'sealed_application_inventory_sha256', 'baseline_backup_inventory_sha256',
            'application_inventory_entries', 'backup_inventory_entries',
            'protected_user_profile_count', 'selected_critical_dependency_count',
            'external_namespace_file_count', 'native_payload_complete_set_count')},
        'signature_status': saved['signature_status'], 'historical_stage_scope': saved['historical_stage_scope'],
        'installed_scope': 'Fresh literal APP gates and fresh installed native outputs; cold data remains literal historical Stale. No source/stage path or status/fingerprint is rebound.',
        'legacy_scope': 'Prior SOURCE +223/cf23 V1/V2 regressions inherited only for byte-identical6c native C/hooks; NOT fresh installed or staged legacy runs.',
        'deployment_limits_and_engineering_holds': saved['deployment_limits'],
        'final_audit': descriptor(audit_path),
        'evidence': {'directory': str(DESTINATION.relative_to(REPOSITORY)),
            'index_sha256': digest(json_bytes(index)), 'indexed_files': len(index['files']),
            'approved_plan_sha256': args.plan_sha256,
            'exact_byte_or_deterministic_gzip_payloads': True,
            'raw_private_inventory_or_runtime_binary_payloads': False}}
    packet.unchanged()
    if not args.check_only:
        packet.publish_new(DESTINATION, SUMMARY, index, summary)
    print(json_bytes({'passed': True, 'check_only': args.check_only,
        'writes': 0 if args.check_only else len(index['files']) + 2,
        'index_sha256': digest(json_bytes(index)), 'summary_sha256': digest(json_bytes(summary)),
        'indexed_files': len(index['files'])}).decode(), end='')


if __name__ == '__main__':
    main()
