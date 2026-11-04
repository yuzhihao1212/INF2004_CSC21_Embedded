"""Offline run evidence from backward-compatible TELEMETRY CSV + JSONL events.

Evaluation statistics may use floats. No code here is imported by fusion/reference.
Percentiles use statistics.quantiles(n=100, method='inclusive'); singletons repeat.
Sequence counters reuse Gateway.track_header verbatim, including its duplicate,
wrap and reboot policy. Exact all-message loss needs datagram events: TELEMETRY
CSV alone omits PONG/ACK sequence numbers. DSP/inference are independent report
maxima; their sum flags conservative bounds, not identifiable per-window misses.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import statistics
from typing import Optional

from mosaic import protocol as p
from mosaic.gateway import Gateway


PERCENTILE_METHOD = "statistics.quantiles(n=100, method='inclusive'); singleton repeated"


def distribution(values):
    if not values:
        return dict(n=0, mean=None, p50=None, p95=None, p99=None, max=None)
    cuts = statistics.quantiles(values, n=100, method='inclusive') if len(values) > 1 else values * 99
    return dict(n=len(values), mean=statistics.fmean(values), p50=cuts[49],
                p95=cuts[94], p99=cuts[98], max=max(values))


def _integer(value, name, low=0, high=2**32 - 1):
    try:
        parsed = int(value)
    except (ValueError, TypeError):
        raise ValueError(f'{name}: expected integer, got {value!r}') from None
    if isinstance(value, (float, bool)) or not low <= parsed <= high:
        raise ValueError(f'{name}: value outside {low}..{high}')
    return parsed


def read_telemetry(path):
    rows = []
    with Path(path).open(newline='', encoding='utf-8-sig') as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            return rows, ['Empty telemetry CSV.']
        missing = {'pc_time', 'node_id', 'seq'} - set(reader.fieldnames)
        if missing:
            raise ValueError('missing required CSV columns: ' + ', '.join(sorted(missing)))
        notes = []
        optional = {'sender_time_ms', 'flags', 'dsp_time_us', 'inference_time_us',
                    'audio_window_seq', 'audio_overruns', 'valid_flags'}
        absent = optional - set(reader.fieldnames)
        if absent:
            notes.append('Unavailable CSV columns: ' + ', '.join(sorted(absent)))
        for line, row in enumerate(reader, 2):
            try:
                wall_ms = datetime.fromisoformat(row['pc_time']).timestamp() * 1000
                if not math.isfinite(wall_ms):
                    raise ValueError('nonfinite pc_time')
                item = {'pc_time': row['pc_time'], 'wall_ms': wall_ms,
                        'node': _integer(row['node_id'], 'node_id', 1, p.MAX_NODES),
                        'seq': _integer(row['seq'], 'seq')}
                for name in optional:
                    value = row.get(name)
                    high = 65535 if name in {'audio_window_seq', 'audio_overruns'} else 255 if name in {'flags', 'valid_flags'} else 2**32 - 1
                    item[name] = _integer(value, name, high=high) if value not in (None, '') else None
                field = next((name for name in ('audio_classes', 'audio_rms', 'audio_prob_pct') if name in row), None)
                item['windows'] = None if field is None else len([x for x in row[field].split(';') if x])
                if item['windows'] is not None and item['windows'] > 2:
                    raise ValueError('more than two audio windows')
                rows.append(item)
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError(f'CSV line {line}: {error}') from None
    return rows, notes


def read_events(path):
    events = []
    if path is None:
        return events
    with Path(path).open(encoding='utf-8') as file:
        for line, text in enumerate(file, 1):
            if not text.strip():
                continue
            try:
                record = json.loads(text)
                if not isinstance(record, dict) or record.get('schema_version', 1) != 1:
                    raise ValueError('unsupported event schema')
                record['monotonic_ms'] = _integer(record['monotonic_ms'], 'monotonic_ms', high=2**63 - 1)
                if not isinstance(record['event'], str):
                    raise ValueError('missing event type')
                record.setdefault('session', 'implicit')
                if not isinstance(record['session'], str):
                    raise ValueError('session must be a string')
                if 'node' in record:
                    record['node'] = _integer(record['node'], 'node', 1, p.MAX_NODES)
                if record['event'] == 'datagram':
                    if 'node' not in record:
                        raise ValueError('datagram requires node')
                    record['seq'] = _integer(record['seq'], 'seq')
                    record['flags'] = _integer(record.get('flags', 0), 'flags', high=255)
                    if record['msg_type'] not in ('TELEMETRY', 'PONG', 'CONFIG_ACK'):
                        raise ValueError('invalid node message type')
                if record['event'] == 'pong':
                    value = record.get('rtt_ms')
                    if 'node' not in record or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                        raise ValueError('RTT must be finite and have a node')
                if record['event'] in {'fusion', 'zone_state'}:
                    if not all(isinstance(record.get(k), str) and record[k] for k in ('region', 'new')):
                        raise ValueError('state event requires region and new state')
                    if record['event'] == 'zone_state' and not isinstance(record.get('zone'), str):
                        raise ValueError('zone state requires zone')
                if record['event'] == 'node_status':
                    if 'node' not in record or record.get('new') not in {'ONLINE', 'STALE', 'OFFLINE'}:
                        raise ValueError('node status requires node and ONLINE/STALE/OFFLINE')
                events.append(record)
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError(f'events line {line}: {error}') from None
    return events


def _replay_headers(records):
    """Returns Gateway counters and per-telemetry metadata, never a second seq algorithm."""
    gateways = {}
    matches = defaultdict(deque)
    for event in records:
        sid, node = event['session'], event['node']
        gateway = gateways.setdefault(sid, Gateway())
        before = gateway.nodes.get(node)
        duplicates = before.duplicates if before else 0
        header = p.Header(p.MsgType[event['msg_type']], node, event['seq'],
                          event.get('sender_time_ms', 0), event.get('flags', 0))
        tracked = gateway.track_header(header, (event.get('source_ip', 'offline'), 0), event['monotonic_ms'] / 1000)
        if header.msg_type == p.MsgType.TELEMETRY:
            matches[(node, header.seq, event.get('csv_pc_time'))].append({
                'session': sid, 'time_ms': event['monotonic_ms'], 'boot': tracked.reboots,
                'duplicate': tracked.duplicates > duplicates})
    return gateways, matches


def _packet_totals(gateways):
    result = defaultdict(Counter)
    for gateway in gateways.values():
        for node, status in gateway.nodes.items():
            for name in ('received', 'lost', 'duplicates', 'reboots'):
                result[node][name] += getattr(status, name)
    return result


def _delivery(counts):
    received, lost, duplicates = (counts.get(k, 0) for k in ('received', 'lost', 'duplicates'))
    total = received + lost
    unique = received - duplicates
    return dict(counts, received=received, lost=lost, duplicates=duplicates, reboots=counts.get('reboots', 0),
                delivery_pct=100 * received / total if total else None,
                loss_pct=100 * lost / total if total else None,
                unique_delivery_pct=100 * unique / (unique + lost) if unique + lost else None,
                unique_loss_pct=100 * lost / (unique + lost) if unique + lost else None)


def _span_events(events):
    grouped = defaultdict(list)
    for event in events:
        grouped[event['session']].append(event)
    spans = {}
    for sid, items in grouped.items():
        starts = [e['monotonic_ms'] for e in items if e['event'] == 'run_start']
        ends = [e['monotonic_ms'] for e in items if e['event'] == 'run_end']
        start = min(starts) if starts else min(e['monotonic_ms'] for e in items)
        end = max(ends) if ends else max(e['monotonic_ms'] for e in items)
        if end < start:
            raise ValueError('run end precedes start')
        spans[sid] = (start, end, bool(ends))
    return grouped, spans


def _state_intervals(events, start, end, initial='UNOBSERVED'):
    intervals, current, at = [], initial, start
    for event in sorted(events, key=lambda e: e['monotonic_ms']):
        time_ms = min(end, max(start, event['monotonic_ms']))
        if time_ms > at:
            intervals.append((at, time_ms, current))
        current, at = event['new'], time_ms
    if end > at:
        intervals.append((at, end, current))
    return intervals


def _state_summary(intervals, transitions):
    times = Counter()
    for a, b, state in intervals:
        times[state] += (b - a) / 1000
    duration = sum(times.values())
    return {'time_s': dict(times), 'time_pct': {k: 100 * v / duration for k, v in times.items()} if duration else {},
            'transition_count': len(transitions), 'transitions': transitions}


def _event_metrics(grouped, spans, nodes):
    availability = {n: Counter() for n in nodes}
    recoveries = defaultdict(list)
    rtts = defaultdict(list)
    regions = defaultdict(list)
    transitions = defaultdict(list)
    intervals_by_region = defaultdict(list)
    for sid, items in grouped.items():
        start, end, _ = spans[sid]
        for node in nodes:
            status_events = [e for e in items if e['event'] == 'node_status' and e['node'] == node]
            for a, b, state in _state_intervals(status_events, start, end):
                availability[node][state] += (b - a) / 1000
            down = None
            for e in status_events:
                if e['new'] == 'OFFLINE' and e.get('old') is not None:
                    down = e['monotonic_ms']
                elif e['new'] == 'ONLINE' and down is not None:
                    recoveries[node].append((e['monotonic_ms'] - down) / 1000)
                    down = None
        per_region = defaultdict(list)
        for event in items:
            kind = event['event']
            if kind == 'pong' and event['rtt_ms'] >= 0:
                rtts[event['node']].append(event['rtt_ms'])
            if kind not in ('fusion', 'zone_state'):
                continue
            key = event['region'] if kind == 'fusion' else f"zone:{event['zone']}:{event['region']}"
            if not isinstance(event.get('new'), str):
                raise ValueError('state event requires a new state')
            per_region[key].append(event)
            if event.get('old') is not None and event['old'] != event['new']:
                transitions[key].append({'session': sid, 'time_s': (event['monotonic_ms'] - start) / 1000,
                    'monotonic_ms': event['monotonic_ms'], 'old': event['old'], 'new': event['new'],
                    'reason': event.get('reason', '')})
        for key, changes in per_region.items():
            intervals = _state_intervals(changes, start, end)
            regions[key].extend(intervals)
            intervals_by_region[(sid, key)] = intervals
    return availability, recoveries, rtts, {k: _state_summary(v, transitions[k]) for k, v in regions.items()}, intervals_by_region


def _warmup(rows):
    episodes = []
    by_stream = defaultdict(list)
    for row in rows:
        by_stream[(row['session'], row['node'])].append(row)
    for (sid, node), stream in by_stream.items():
        active = None
        previous_boot = None
        last_time = None
        for row in stream:
            if row['duplicate']:
                continue
            if active is not None and row['boot'] != previous_boot:
                episodes.append(dict(session=sid, node=node, observed_s=(last_time - active) / 1000, complete=False))
                active = None
            flags = row['valid_flags']
            time_ms = row['time_ms']
            if flags is None and active is not None:
                episodes.append(dict(session=sid, node=node, observed_s=(last_time - active) / 1000, complete=False))
                active = None
            if flags is not None:
                valid = bool(flags & p.Valid.CO2)
                warming = bool(flags & p.Valid.CO2_WARMUP) and not valid
                if warming and active is None:
                    active = time_ms
                if not warming and active is not None:
                    episodes.append(dict(session=sid, node=node, observed_s=(time_ms - active) / 1000, complete=valid))
                    active = None
            previous_boot, last_time = row['boot'], time_ms
        if active is not None:
            episodes.append(dict(session=sid, node=node, observed_s=(last_time - active) / 1000, complete=False))
    return {'episodes': episodes, 'observed_s': sum(e['observed_s'] for e in episodes),
            'completed_s': sum(e['observed_s'] for e in episodes if e['complete']),
            'censored_episodes': sum(not e['complete'] for e in episodes)}


def _telemetry_metrics(rows, deadline_us):
    unique = [r for r in rows if not r['duplicate']]
    intervals, skipped, overruns, windows = [], 0, 0, 0
    audio_available = all(r['windows'] is not None and r['audio_window_seq'] is not None for r in unique) and bool(unique)
    overruns_available = all(r['audio_overruns'] is not None for r in unique) and bool(unique)
    previous = {}
    for row in unique:
        key = row['session'], row['node']
        prev = previous.get(key)
        same_boot = prev is not None and prev['boot'] == row['boot'] and not (row['flags'] or 0) & p.FLAG_FIRST_SINCE_BOOT
        if same_boot:
            delta_ms = row['time_ms'] - prev['time_ms']
            if delta_ms >= 0:
                intervals.append(delta_ms)
        if row['windows'] is not None:
            count = row['windows']
            if audio_available and same_boot:
                delta = (row['audio_window_seq'] - prev['audio_window_seq']) % 65536
                skipped += max(0, delta - count)
                count = min(count, delta)
            windows += count
        if overruns_available and same_boot:
            overruns += (row['audio_overruns'] - prev['audio_overruns']) % 65536
        previous[key] = row
    stats = distribution(intervals)
    stats['jitter_ms'] = stats['p95'] - stats['p50'] if intervals else None
    checked = [r for r in unique if r['dsp_time_us'] is not None and r['inference_time_us'] is not None]
    exceed = [r for r in checked if r['dsp_time_us'] + r['inference_time_us'] > deadline_us]
    return {'telemetry_reports': len(rows), 'unique_telemetry_reports': len(unique), 'interval_ms': stats,
            'dsp_us': distribution([r['dsp_time_us'] for r in unique if r['dsp_time_us'] is not None]),
            'inference_us': distribution([r['inference_time_us'] for r in unique if r['inference_time_us'] is not None]),
            'deadline': {'threshold_us': deadline_us, 'reports_checked': len(checked), 'reports_exceeding': len(exceed),
                         'potential_affected_windows_upper_bound': sum(r['windows'] for r in exceed)
                            if all(r['windows'] is not None for r in exceed) else None,
                         'actual_window_misses': None},
            'audio': {'windows_received': windows if all(r['windows'] is not None for r in unique) and unique else None,
                      'skipped_windows': skipped if audio_available else None,
                      'overruns_increase': overruns if overruns_available else None},
            'co2_warmup': _warmup(unique) if any(r['valid_flags'] is not None for r in unique) else None}


def read_expected(path):
    labels = []
    with Path(path).open(newline='', encoding='utf-8-sig') as file:
        reader = csv.DictReader(file)
        if not {'start_s', 'end_s', 'region', 'expected_state'} <= set(reader.fieldnames or []):
            raise ValueError('expected timeline needs start_s,end_s,region,expected_state')
        for line, row in enumerate(reader, 2):
            try:
                start, end = float(row['start_s']), float(row['end_s'])
                region, expected = row['region'].strip(), row['expected_state'].strip()
                if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end or not region or not expected:
                    raise ValueError('invalid label interval/state')
                labels.append((start, end, region, expected))
            except (ValueError, TypeError) as error:
                raise ValueError(f'expected line {line}: {error}') from None
    last = {}
    for start, end, region, state in sorted(labels):
        if start < last.get(region, 0):
            raise ValueError(f'overlapping expected intervals in {region}')
        last[region] = end
    return labels


def _score(labels, spans, intervals):
    if len(spans) != 1:
        raise ValueError('--expected requires exactly one event-log session')
    sid, (begin, end, _) = next(iter(spans.items()))
    by_region = {}
    for start, stop, region, expected in labels:
        result = by_region.setdefault(region, {'labelled_s': 0, 'correct_s': 0, 'unobserved_s': 0, 'states': {}})
        a, b = max(begin, begin + start * 1000), min(end, begin + stop * 1000)
        if b <= a:
            continue
        pieces = intervals.get((sid, region), [(begin, end, 'UNOBSERVED')])
        for x, y, actual in pieces:
            duration = max(0, min(b, y) - max(a, x)) / 1000
            if duration == 0:
                continue
            result['labelled_s'] += duration
            result['correct_s'] += duration if expected == actual else 0
            result['unobserved_s'] += duration if actual == 'UNOBSERVED' else 0
            for state in {expected, actual}:
                counts = result['states'].setdefault(state, {'tp_s': 0, 'fp_s': 0, 'fn_s': 0})
                counts['tp_s'] += duration if state == expected == actual else 0
                counts['fp_s'] += duration if state == actual and state != expected else 0
                counts['fn_s'] += duration if state == expected and state != actual else 0
    for result in by_region.values():
        result['accuracy_pct'] = 100 * result['correct_s'] / result['labelled_s'] if result['labelled_s'] else None
        result['false_positive_s'] = sum(s['fp_s'] for s in result['states'].values())
        result['false_negative_s'] = sum(s['fn_s'] for s in result['states'].values())
    total = sum(r['labelled_s'] for r in by_region.values())
    correct = sum(r['correct_s'] for r in by_region.values())
    return {'regions': by_region, 'labelled_region_seconds': total,
            'accuracy_pct': 100 * correct / total if total else None}


def evaluate(csv_path, events_path=None, *, deadline_ms=400, expected_path=None):
    if isinstance(deadline_ms, bool) or not math.isfinite(deadline_ms) or deadline_ms <= 0:
        raise ValueError('deadline-ms must be finite and positive')
    rows, notes = read_telemetry(csv_path)
    events = read_events(events_path)
    headers = [e for e in events if e['event'] == 'datagram']
    exact = bool(headers)
    if not exact:
        notes.append('Loss is a TELEMETRY-only sequence estimate: unlogged PONG/ACK seqs may appear lost; use --events for exact tracking.')
        headers = [dict(event='datagram', session='csv', monotonic_ms=r['wall_ms'], node=r['node'],
                        seq=r['seq'], flags=r['flags'] or 0, msg_type='TELEMETRY', csv_pc_time=r['pc_time']) for r in rows]
    gateways, matches = _replay_headers(headers)
    for row in rows:
        key = row['node'], row['seq'], row['pc_time']
        if not matches[key]:
            raise ValueError('CSV/event mismatch: missing TELEMETRY header for ' + str(key))
        row.update(matches[key].popleft())
    if exact and sum(len(v) for v in matches.values()):
        raise ValueError('CSV/event mismatch: event TELEMETRY header has no CSV row')
    grouped, spans = _span_events(events)
    if not spans and rows:
        spans = {'csv': (min(r['time_ms'] for r in rows), max(r['time_ms'] for r in rows), False)}
    nodes = {r['node'] for r in rows} | {e['node'] for e in events if 'node' in e}
    for e in events:
        if e['event'] == 'run_start':
            nodes.update(_integer(n, 'configured node', 1, p.MAX_NODES) for n in e.get('nodes', {}))
    availability, recovery, rtts, regions, intervals = _event_metrics(grouped, spans, nodes)
    packet_counts = _packet_totals(gateways)
    result = {'schema_version': 1, 'percentile_method': PERCENTILE_METHOD,
              'duration_s': sum((b - a) / 1000 for a, b, _ in spans.values()),
              'sessions': {sid: {'start_ms': a, 'end_ms': b, 'closed': closed} for sid, (a, b, closed) in spans.items()},
              'sequence_source': 'all-message events' if exact else 'telemetry-only CSV estimate',
              'notes': notes, 'nodes': {}, 'fusion': regions}
    if not events:
        notes.append('RTT, recovery, availability and fusion states unavailable without an event log.')
    if any(e['event'] == 'pong' and e['rtt_ms'] < 0 for e in events):
        notes.append('Negative RTT observations were excluded from latency statistics; raw events retain them.')
    if any(not closed for _, _, closed in spans.values()):
        notes.append('A session has no run_end; durations stop at the last recorded observation (right-censored).')
    notes.append('DSP/inference percentiles describe report maxima. Sum of independent maxima flags potential exceedances; actual per-window deadline misses are UNVERIFIED.')
    for node in sorted(nodes):
        metrics = _telemetry_metrics([r for r in rows if r['node'] == node], deadline_ms * 1000)
        times = availability[node]
        if times:
            for state in ('ONLINE', 'STALE', 'OFFLINE'):
                times.setdefault(state, 0)
        duration = sum(times.values())
        metrics.update(packets=_delivery(packet_counts[node]), rtt_ms=distribution(rtts[node]),
                       recovery_s=distribution(recovery[node]) | {'samples_s': recovery[node]},
                       availability={'time_s': dict(times), 'pct': {k: 100 * v / duration for k, v in times.items()} if duration else {}})
        result['nodes'][str(node)] = metrics
    overall = _telemetry_metrics(rows, deadline_ms * 1000)
    all_counts = sum(packet_counts.values(), Counter())
    all_times = sum(availability.values(), Counter())
    node_seconds = sum(all_times.values())
    if node_seconds:
        for state in ('ONLINE', 'STALE', 'OFFLINE'):
            all_times.setdefault(state, 0)
    overall.update(packets=_delivery(all_counts), rtt_ms=distribution([v for vs in rtts.values() for v in vs]),
                   recovery_s=distribution([v for vs in recovery.values() for v in vs])
                              | {'samples_s': [v for vs in recovery.values() for v in vs]},
                   availability={'time_s': dict(all_times), 'pct': {k: 100 * v / node_seconds for k, v in all_times.items()} if node_seconds else {}})
    result['overall'] = overall
    result['events'] = {'counts': dict(Counter(e['event'] for e in events)),
                        'drops_by_source': dict(Counter(e.get('source_ip', 'unknown') for e in events if e['event'] == 'drop')),
                        'config': [e for e in events if e['event'] == 'config'],
                        'status_changes': [e for e in events if e['event'] == 'node_status'],
                        'reference': [e for e in events if e['event'] == 'reference']}
    if expected_path is not None:
        if not events:
            raise ValueError('--expected requires --events with fusion state changes')
        result['scoring'] = _score(read_expected(expected_path), spans, intervals)
    return result


def _fmt(value):
    if value is None:
        return '—'
    if isinstance(value, float):
        return f'{value:.3f}'.rstrip('0').rstrip('.')
    return str(value).replace('|', '\\|').replace('\n', ' ')


def _table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |']
                     + ['| ' + ' | '.join(_fmt(v) for v in row) + ' |' for row in rows])


def markdown(summary):
    scopes = [('Overall', summary['overall'])] + [(f'Node {n}', m) for n, m in summary['nodes'].items()]
    config = summary['events']['config']
    reference = summary['events']['reference']
    parts = ['# MOSAIC test-run evaluation',
             f"Observed duration: {_fmt(summary['duration_s'])} s. Telemetry rows: {summary['overall']['telemetry_reports']}. Nodes: {len(summary['nodes'])}.",
             'Percentiles: ' + summary['percentile_method'] + '.', 'Sequence source: ' + summary['sequence_source'] + '.',
             '## Packet delivery',
             _table(['Scope', 'Received', 'Missing', 'Duplicates', 'Reboots', 'Unique delivery %', 'Unique loss %', 'Gateway loss %'],
                    [(name, m['packets']['received'], m['packets']['lost'], m['packets']['duplicates'], m['packets']['reboots'], m['packets']['unique_delivery_pct'], m['packets']['unique_loss_pct'], m['packets']['loss_pct']) for name, m in scopes]),
             'Unique delivery/loss excludes duplicates. Gateway loss matches NodeState.loss_pct; its received count includes duplicates. Counters share the live sequence tracker.',
             '## Report timing', _table(['Scope', 'Intervals', 'Mean ms', 'Jitter p95−p50 ms'],
                    [(name, m['interval_ms']['n'], m['interval_ms']['mean'], m['interval_ms']['jitter_ms']) for name, m in scopes]),
             '## Processing time (report maxima)', _table(['Scope', 'Metric', 'p50 µs', 'p95 µs', 'p99 µs', 'Max µs'],
                    [(name, metric, *(m[key][k] for k in ('p50', 'p95', 'p99', 'max'))) for name, m in scopes for metric, key in [('DSP', 'dsp_us'), ('Inference', 'inference_us')]]),
             '## Deadline bounds', _table(['Scope', 'Deadline µs', 'Reports checked', 'Reports flagged', 'Potential windows (upper bound)'],
                    [(name, *(m['deadline'][k] for k in ('threshold_us', 'reports_checked', 'reports_exceeding', 'potential_affected_windows_upper_bound'))) for name, m in scopes]),
             'Exact missed-window counts are **UNVERIFIED**: v2 sends independent DSP/inference maxima, not paired per-window times.',
             '## Audio', _table(['Scope', 'Windows received', 'Skipped windows', 'Overruns increase'],
                    [(name, *(m['audio'][k] for k in ('windows_received', 'skipped_windows', 'overruns_increase'))) for name, m in scopes]),
             '## Network and availability', _table(['Scope', 'RTT p50 ms', 'RTT p95 ms', 'RTT max ms', 'Recovery p50 s', 'Recovery max s', 'ONLINE %', 'STALE %', 'OFFLINE %', 'Unobserved %'],
                    [(name, *(m['rtt_ms'][k] for k in ('p50', 'p95', 'max')), m['recovery_s']['p50'], m['recovery_s']['max'],
                      *(m['availability']['pct'].get(k, 0) if m['availability']['pct'] else None for k in ('ONLINE', 'STALE', 'OFFLINE', 'UNOBSERVED'))) for name, m in scopes]),
             'Availability uses observed status events. Overall availability is weighted by node-seconds; recovery excludes initial discovery and unfinished outages.',
             '## CO₂ warm-up', _table(['Scope', 'Observed warm-up s', 'Completed warm-up s', 'Unfinished episodes'],
                    [(name, m['co2_warmup']['observed_s'] if m['co2_warmup'] else None,
                      m['co2_warmup']['completed_s'] if m['co2_warmup'] else None,
                      m['co2_warmup']['censored_episodes'] if m['co2_warmup'] else None) for name, m in scopes]),
             'Observed duration starts at the first warm-up report, not power-on. Unfinished episodes are lower bounds; overall is summed node-seconds.',
             '## CONFIG delivery', _table(['Node', 'Requests/resends', 'Attempts', 'Applied', 'Failed', 'Rejected', 'Stale'],
                [(node, sum(e['node']==int(node) and e['state']=='sending' and 'attempt' not in e for e in config),
                  sum(e['node']==int(node) and 'attempt' in e for e in config),
                  *(sum(e['node']==int(node) and e['state']==state for e in config) for state in ('applied','failed','rejected','stale')))
                 for node in summary['nodes']]),
             '## Reference calibration', _table(['Zone', 'Starts/restarts', 'Ready', 'Resets'],
                [(zone, *(sum(e['zone']==zone and e['action']==action for e in reference) for action in ('start','ready','reset')))
                 for zone in sorted({e['zone'] for e in reference})]),
             '## Dropped datagrams', _table(['Source IP', 'Dropped'], sorted(summary['events']['drops_by_source'].items())),
             '## Fusion states', _table(['Region', 'State', 'Time s', 'Time %', 'Transitions in region'],
                    [(region, state, time_s, data['time_pct'][state], data['transition_count']) for region, data in summary['fusion'].items() for state, time_s in data['time_s'].items()]),
             '## Transition list', _table(['Session', 'Time s', 'Region', 'Old', 'New', 'Reason'],
                    sorted([(e['session'][:8], e['time_s'], region, e['old'], e['new'], e['reason']) for region, data in summary['fusion'].items() for e in data['transitions']],
                           key=lambda row: (row[0], row[1], row[2])))]
    if 'scoring' in summary:
        parts += ['## Labelled-timeline recognition', _table(['Region', 'Labelled s', 'Accuracy %', 'False-positive s', 'False-negative s', 'Unobserved s'],
            [(region, d['labelled_s'], d['accuracy_pct'], d['false_positive_s'], d['false_negative_s'], d['unobserved_s']) for region, d in summary['scoring']['regions'].items()]),
            _table(['Region', 'State (one vs rest)', 'TP s', 'FP s', 'FN s'],
            [(region, state, d['tp_s'], d['fp_s'], d['fn_s']) for region, r in summary['scoring']['regions'].items() for state, d in r['states'].items()]),
            'Only labelled time inside the capture is scored. Gaps are unscored; unavailable state is incorrect. Multiclass errors add one FP for actual and one FN for expected.']
    parts += ['## Data limits', '\n'.join('- ' + note for note in summary['notes'])]
    return '\n\n'.join(parts) + '\n'


def main(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('telemetry', help='TELEMETRY CSV emitted by gateway/dashboard --csv')
    parser.add_argument('--events', help='JSONL emitted by --events')
    parser.add_argument('--out', help='Markdown output (stdout if omitted)')
    parser.add_argument('--json', dest='json_out', help='JSON summary output')
    parser.add_argument('--deadline-ms', type=float, default=400)
    parser.add_argument('--expected', help='human labels: start_s,end_s,region,expected_state')
    args = parser.parse_args(argv)
    try:
        inputs = {Path(path).resolve() for path in (args.telemetry, args.events, args.expected) if path}
        outputs = [Path(path).resolve() for path in (args.out, args.json_out) if path]
        if len(set(outputs)) != len(outputs) or any(path in inputs for path in outputs):
            raise ValueError('outputs must be distinct and must not overwrite input evidence')
        summary = evaluate(args.telemetry, args.events, deadline_ms=args.deadline_ms, expected_path=args.expected)
        report = markdown(summary)
        if args.out:
            Path(args.out).write_text(report, encoding='utf-8')
        else:
            print(report, end='')
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
