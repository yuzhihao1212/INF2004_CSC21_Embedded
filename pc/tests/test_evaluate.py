"""Synthetic evidence fixtures plus real local UDP simulator capture."""
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import select
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

from mosaic import protocol as p
from mosaic.evaluate import distribution, evaluate, main, markdown
from mosaic.fusion import FusionConfig, FusionEngine
from mosaic.gateway import CSV_FIELDS, Gateway, GatewayServer, csv_row
from mosaic.simulator import Simulator

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def stamp(seconds):
    return (BASE + timedelta(seconds=seconds)).isoformat(timespec='milliseconds')


def row(seconds=0, seq=0, node=1, windows=2, **kwargs):
    header = p.Header(p.MsgType.TELEMETRY, node, seq, round(seconds * 1000))
    header.flags = kwargs.pop('flags', 0)
    telemetry = p.Telemetry(audio=tuple(p.AudioWindow(160, p.AudioClass.LECTURER_SPEECH,
        (5, 85, 5, 5)) for _ in range(windows)), **kwargs)
    return dict(zip(CSV_FIELDS, csv_row(header, telemetry, stamp(seconds))))


def event(kind, seconds=0, session='one', **kwargs):
    return dict(schema_version=1, session=session, wall_time=stamp(seconds),
                monotonic_ms=round(seconds * 1000), event=kind, **kwargs)


def packet(record, seconds, kind='TELEMETRY', session='one'):
    return event('datagram', seconds, session, node=int(record['node_id']), msg_type=kind,
        seq=int(record['seq']), flags=int(record['flags']), sender_time_ms=int(record['sender_time_ms']),
        csv_pc_time=record['pc_time'] if kind == 'TELEMETRY' else None)


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv = self.root / 'run.csv'
        self.events = self.root / 'run.jsonl'

    def capture(self, rows, events=None, columns=CSV_FIELDS):
        with self.csv.open('w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        if events is not None:
            self.events.write_text(''.join(json.dumps(e) + '\n' for e in events))
        return evaluate(self.csv, self.events if events is not None else None)

    def test_sequence_loss_duplicate_reboot_and_audio_wrap(self):
        rows = [row(0, 0, flags=p.FLAG_FIRST_SINCE_BOOT, audio_window_seq=65534, audio_overruns=65534,
                    dsp_time_us=100000, inference_time_us=100000),
                row(1, 1, audio_window_seq=0, audio_overruns=65535, dsp_time_us=200000, inference_time_us=100000),
                row(1.1, 1, audio_window_seq=0, audio_overruns=65535, dsp_time_us=200000, inference_time_us=100000),
                row(2, 4, audio_window_seq=4, audio_overruns=1, dsp_time_us=300000, inference_time_us=100000),
                row(3, 0, windows=1, flags=p.FLAG_FIRST_SINCE_BOOT, audio_window_seq=1,
                    dsp_time_us=400000, inference_time_us=100000),
                row(4, 1, audio_window_seq=3, audio_overruns=1, dsp_time_us=500000, inference_time_us=100000)]
        result = self.capture(rows)['nodes']['1']
        self.assertEqual({k: result['packets'][k] for k in ('received', 'lost', 'duplicates', 'reboots')},
                         dict(received=5, lost=2, duplicates=1, reboots=1))
        self.assertAlmostEqual(result['packets']['loss_pct'], 200 / 7)
        self.assertAlmostEqual(result['packets']['unique_delivery_pct'], 500 / 7)
        self.assertEqual(result['audio'], dict(windows_received=9, skipped_windows=2, overruns_increase=4))
        self.assertEqual(result['interval_ms']['mean'], 1000)
        self.assertEqual(result['interval_ms']['n'], 3)
        self.assertEqual(result['dsp_us']['p50'], 300000)
        self.assertEqual(result['dsp_us']['p95'], 480000)
        self.assertEqual(result['dsp_us']['p99'], 496000)
        self.assertEqual(result['deadline']['reports_exceeding'], 2)
        self.assertEqual(result['deadline']['potential_affected_windows_upper_bound'], 3)
        self.assertIsNone(result['deadline']['actual_window_misses'])

    def test_all_message_sequence_tracking_avoids_phantom_pong_ack_loss(self):
        first, last = row(0, 0), row(1, 3)
        events = [event('run_start', nodes={'1':'A'}), packet(first, 0),
                  packet(row(.2, 1), .2, 'PONG'), event('pong', .2, node=1, rtt_ms=12.5),
                  packet(row(.4, 2), .4, 'CONFIG_ACK'), packet(last, 1), event('run_end', 2)]
        exact = self.capture([first, last], events)
        self.assertEqual(exact['nodes']['1']['packets']['received'], 4)
        self.assertEqual(exact['nodes']['1']['packets']['lost'], 0)
        self.assertEqual(exact['nodes']['1']['rtt_ms']['p95'], 12.5)
        estimate = self.capture([first, last])
        self.assertEqual(estimate['nodes']['1']['packets']['lost'], 2)
        self.assertIn('estimate', estimate['sequence_source'])

    def test_packet_wrap_and_reboot_match_live_gateway(self):
        records = [row(0, 2**32-2), row(1, 0), row(2, 1), row(3, 1), row(4, 0, flags=1)]
        actual = self.capture(records)['nodes']['1']['packets']
        live = Gateway()
        for i, r in enumerate(records):
            live.handle(p.encode(p.Header(p.MsgType.TELEMETRY, 1, r['seq'], r['sender_time_ms'], r['flags']), p.Telemetry()),
                        ('127.0.0.1', 0), i)
        for key in ('received', 'lost', 'duplicates', 'reboots', 'loss_pct'):
            self.assertEqual(actual[key], getattr(live.nodes[1], key))

    def test_availability_recovery_and_rtt(self):
        events = [event('run_start', nodes={'1':'A'}),
            event('node_status', 0, node=1, old=None, new='ONLINE'),
            event('node_status', 3, node=1, old='ONLINE', new='STALE'),
            event('node_status', 10, node=1, old='STALE', new='OFFLINE'),
            event('node_status', 12, node=1, old='OFFLINE', new='ONLINE'),
            event('pong', 1, node=1, rtt_ms=10), event('pong', 2, node=1, rtt_ms=20), event('run_end', 20)]
        node = self.capture([row()], events)['nodes']['1']
        self.assertEqual(node['availability']['pct'], dict(ONLINE=55, STALE=35, OFFLINE=10))
        self.assertEqual(node['recovery_s']['p50'], 2)
        self.assertEqual(node['rtt_ms']['p95'], 19.5)

    def test_initial_discovery_is_not_a_network_recovery(self):
        events = [event('run_start'), event('node_status', node=1, old=None, new='OFFLINE'),
                  event('node_status', 2, node=1, old='OFFLINE', new='ONLINE'), event('run_end', 4)]
        self.assertEqual(self.capture([row()], events)['nodes']['1']['recovery_s']['n'], 0)

    def test_completed_and_censored_co2_warmup(self):
        rows = [row(0, 0, valid_flags=p.Valid.CO2_WARMUP), row(4, 1, valid_flags=p.Valid.CO2_WARMUP),
                row(5, 2, valid_flags=p.Valid.CO2), row(6, 0, flags=1, valid_flags=p.Valid.CO2_WARMUP),
                row(8, 1, valid_flags=p.Valid.CO2_WARMUP)]
        warm = self.capture(rows)['nodes']['1']['co2_warmup']
        self.assertEqual((warm['observed_s'], warm['completed_s'], warm['censored_episodes']), (7, 5, 1))

    def test_fusion_zone_times_transitions_and_expected_scoring(self):
        events = [event('run_start'), event('fusion', region='activity', old=None, new='UNKNOWN'),
                  event('fusion', 2, region='activity', old='UNKNOWN', new='QUIET', reason='motion'),
                  event('fusion', 6, region='activity', old='QUIET', new='FOCUSED_LECTURE', reason='speech'),
                  event('zone_state', zone='C', region='activity', old=None, new='NO_DATA'),
                  event('zone_state', 3, zone='C', region='activity', old='NO_DATA', new='STILL'),
                  event('zone_state', 7, zone='C', region='activity', old='STILL', new='TALKING'), event('run_end', 10)]
        result = self.capture([row()], events)
        self.assertEqual(result['fusion']['activity']['time_s'], {'UNKNOWN':2, 'QUIET':4, 'FOCUSED_LECTURE':4})
        self.assertEqual(result['fusion']['zone:C:activity']['time_s']['TALKING'], 3)
        self.assertEqual(result['fusion']['activity']['transition_count'], 2)
        self.assertEqual(result['fusion']['activity']['transitions'][0]['reason'], 'motion')
        labels = self.root / 'labels.csv'
        labels.write_text('start_s,end_s,region,expected_state\n0,5,activity,QUIET\n5,10,activity,FOCUSED_LECTURE\n')
        scored = evaluate(self.csv, self.events, expected_path=labels)['scoring']
        self.assertEqual(scored['accuracy_pct'], 70)
        activity = scored['regions']['activity']
        self.assertEqual((activity['false_positive_s'], activity['false_negative_s']), (3, 3))
        self.assertEqual(activity['states']['QUIET'], {'tp_s':3, 'fp_s':1, 'fn_s':2})

    def test_expected_clips_outside_capture_and_rejects_overlap(self):
        self.capture([row()], [event('run_start'), event('run_end', 10)])
        labels = self.root / 'labels.csv'
        labels.write_text('start_s,end_s,region,expected_state\n5,20,activity,QUIET\n')
        score = evaluate(self.csv, self.events, expected_path=labels)['scoring']['regions']['activity']
        self.assertEqual((score['labelled_s'], score['unobserved_s'], score['accuracy_pct']), (5,5,0))
        labels.write_text('start_s,end_s,region,expected_state\n0,5,activity,QUIET\n4,10,activity,QUIET\n')
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            evaluate(self.csv, self.events, expected_path=labels)

    def test_appended_sessions_do_not_count_between_run_gaps(self):
        a, b = row(0, 1), row(100, 100)
        events = [event('run_start'), packet(a, 0), event('run_end', 10),
                  event('run_start', 100, session='two'), packet(b, 100, session='two'), event('run_end', 110, session='two')]
        summary = self.capture([a,b], events)
        self.assertEqual(summary['duration_s'], 20)
        self.assertEqual(summary['overall']['packets']['lost'], 0)
        self.assertEqual(summary['overall']['interval_ms']['n'], 0)

    def test_monotonic_events_survive_wall_clock_steps(self):
        a, b = row(10, 0), row(1, 1)
        events = [event('run_start'), packet(a, 0), packet(b, 1), event('run_end', 2)]
        self.assertEqual(self.capture([a,b], events)['overall']['interval_ms']['mean'], 1000)

    def test_empty_and_missing_columns(self):
        self.csv.write_text('')
        result = evaluate(self.csv)
        self.assertEqual((result['nodes'], result['overall']['telemetry_reports']), ({}, 0))
        self.assertIsNone(result['overall']['packets']['delivery_pct'])
        self.capture([row()], columns=('pc_time','node_id','seq'))
        node = evaluate(self.csv)['nodes']['1']
        self.assertIsNone(node['audio']['skipped_windows'])
        self.assertEqual(node['dsp_us']['n'], 0)
        self.csv.write_text('pc_time,node_id\n2026-01-01,1\n')
        with self.assertRaisesRegex(ValueError, 'seq'):
            evaluate(self.csv)

    def test_bad_cells_events_and_mismatched_capture(self):
        for changes in ({'seq':'NaN'}, {'node_id':9}, {'pc_time':'yesterday'}, {'audio_classes':'a;b;c'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.capture([row() | changes])
        self.capture([row()])
        self.events.write_text('{bad json\n')
        with self.assertRaisesRegex(ValueError, 'events line 1'):
            evaluate(self.csv, self.events)
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            self.capture([row()], [packet(row(seq=2), 0)])
        with self.assertRaises(ValueError):
            evaluate(self.csv, deadline_ms=float('nan'))

    def test_cli_writes_markdown_and_json(self):
        self.capture([row()])
        report, summary = self.root/'report.md', self.root/'summary.json'
        main([str(self.csv), '--out', str(report), '--json', str(summary), '--deadline-ms', '1'])
        self.assertIn('Packet delivery', report.read_text())
        self.assertIn('UNVERIFIED', report.read_text())
        self.assertEqual(json.loads(summary.read_text())['overall']['telemetry_reports'], 1)

    def test_percentile_method_small_samples(self):
        self.assertEqual(distribution([4])['p99'], 4)
        self.assertEqual(distribution([0,100])['p95'], 95)

    def test_missing_state_fields_and_negative_rtt(self):
        with self.assertRaisesRegex(ValueError, 'state event'):
            self.capture([row()], [event('fusion', new='QUIET')])
        result = self.capture([row()], [event('pong', node=1, rtt_ms=-1), event('run_end', 1)])
        self.assertEqual(result['overall']['rtt_ms']['n'], 0)
        self.assertTrue(any('Negative RTT' in note for note in result['notes']))

    def test_large_audio_sequence_delta_uses_protocol_modulo_formula(self):
        result = self.capture([row(0,0,audio_window_seq=0), row(1,1,audio_window_seq=35000)])
        self.assertEqual(result['overall']['audio']['skipped_windows'], 34998)

    def test_outputs_cannot_overwrite_capture(self):
        self.capture([row()])
        before = self.csv.read_bytes()
        with patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit):
            main([str(self.csv), '--out', str(self.csv)])
        self.assertEqual(self.csv.read_bytes(), before)


class EventCapture(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.clock = patch('mosaic.gateway.time.monotonic', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.events, self.csv = io.StringIO(), io.StringIO()
        self.server = GatewayServer(('127.0.0.1',0), out=io.StringIO(),
            csv_file=self.csv, events_file=self.events, fusion=FusionEngine(FusionConfig(zone_dwell_ms=0)))
        self.addCleanup(self.server.close)

    def send(self, seq, node=1, msg=p.MsgType.TELEMETRY, payload=None, flags=0):
        payload = p.Telemetry() if payload is None else payload
        header = p.Header(msg, node, seq, round(self.now * 1000), flags)
        self.server._received(p.encode(header, payload), ('127.0.0.1',5006), self.now)

    @property
    def records(self):
        return [json.loads(line) for line in self.events.getvalue().splitlines()]

    def test_retry_events_and_csv_replay_match_live_counts(self):
        data = p.encode(p.Header(p.MsgType.TELEMETRY, 1, 0, 0), p.Telemetry(co2_ppm=600))
        self.server._received(data, ('127.0.0.1', 5006), 0)
        self.now = 0.1
        self.server._received(data, ('127.0.0.1', 5006), self.now)
        self.now = 2
        self.send(2, payload=p.Telemetry(co2_ppm=800))
        self.now = 2.1
        late = p.encode(p.Header(p.MsgType.TELEMETRY, 1, 1, 1000), p.Telemetry(co2_ppm=700))
        self.server._received(late, ('127.0.0.1', 5006), self.now)
        self.server.close()
        self.assertEqual(self.server.gateway.nodes[1].telemetry.co2_ppm, 800)
        packets = [e for e in self.records if e['event'] == 'datagram']
        self.assertEqual(len(packets), 4)  # Duplicates remain in raw event evidence.
        self.assertEqual(sum(e.get('accepted') is False for e in packets), 1)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(self.csv.getvalue())))), 3)
        with tempfile.TemporaryDirectory() as d:
            capture = Path(d) / 'capture.csv'
            events = Path(d) / 'events.jsonl'
            capture.write_text(self.csv.getvalue())
            events.write_text(self.events.getvalue())
            counts = evaluate(capture, events)['nodes']['1']['packets']
        self.assertEqual((counts['received'], counts['lost'], counts['duplicates'],
                          counts['recovered'], counts['gaps_detected']), (3, 0, 1, 1, 1))

    def test_all_event_envelopes_csv_compatibility_pong_drop_status(self):
        self.send(0)
        self.now = 1
        self.send(1, msg=p.MsgType.PONG, payload=p.Ping(975000))
        self.server._received(b'bad', ('127.0.0.2',1), self.now)
        self.now = 5
        self.server._log_statuses(self.now)
        self.now = 12
        self.server._log_statuses(self.now)
        self.now = 13
        self.send(2)
        self.server.close()
        kinds = {e['event'] for e in self.records}
        self.assertTrue({'run_start','run_end','datagram','pong','drop','node_status','fusion','zone_state'} <= kinds)
        self.assertEqual(next(e for e in self.records if e['event']=='pong')['rtt_ms'], 25)
        self.assertEqual(next(e for e in self.records if e['event']=='drop')['source_ip'], '127.0.0.2')
        self.assertEqual([e['new'] for e in self.records if e['event']=='node_status' and e['node']==1],
                         ['OFFLINE','ONLINE','STALE','OFFLINE','ONLINE'])
        for e in self.records:
            self.assertIsNotNone(datetime.fromisoformat(e['wall_time']).tzinfo)
            self.assertIsInstance(e['monotonic_ms'], int)
        expected_header = 'pc_time,node_id,seq,sender_time_ms,flags,temperature_c,humidity_pct,dsp_time_us,inference_time_us,free_heap_bytes,co2_ppm,config_version,audio_overruns,audio_window_seq,audio_classes,audio_prob_pct,audio_rms,pir_active_pct,valid_flags,cpu_load_pct,wifi_rssi_dbm'.split(',')
        self.assertEqual(CSV_FIELDS, expected_header)
        self.assertEqual(next(csv.reader(io.StringIO(self.csv.getvalue()))), expected_header)

    def test_config_sending_stale_applied_rejected_failed(self):
        self.send(0)
        cfg = self.server.set_config(1, report_interval_ms=2000)
        self.send(1, msg=p.MsgType.CONFIG_ACK, payload=p.ConfigAck(cfg.config_version, p.AckStatus.STALE_VERSION))
        cfg = self.server.gateway.nodes[1].config.config
        self.send(2, payload=p.Telemetry(config_version=cfg.config_version))
        cfg = self.server.set_config(1, report_interval_ms=500)
        self.send(3, msg=p.MsgType.CONFIG_ACK, payload=p.ConfigAck(cfg.config_version, p.AckStatus.INVALID_VALUE))
        self.server.set_config(1, report_interval_ms=1000)
        for i in range(6):
            self.now = i / 2
            self.server.gateway.config_sends(self.now)
        self.server._flush_config_events()
        states = {e['state'] for e in self.records if e['event']=='config'}
        self.assertEqual(states, {'sending','stale','applied','rejected','failed'})

    def test_reference_start_ready_restart_reset_and_zone_changes(self):
        self.server.fusion.calibrate(0)
        self.server.reference_operation('start', None, 0)
        for i in range(20):
            self.now += .5
            for node in (1,3):
                level = (40 + i * 2) * (16 if node == 1 else 8)
                self.send(i+1, node, payload=p.Telemetry(audio_window_seq=i+1,
                    audio=(p.AudioWindow(level,p.AudioClass.LECTURER_SPEECH,(5,85,5,5)),)))
            self.server._evaluate_fusion(self.now)
        self.server.fusion.calibrate(self.now, 'C')
        self.server.reference_operation('start','C',self.now)
        self.server.fusion.reset_reference('C')
        self.server.reference_operation('reset','C',self.now)
        actions = [e['action'] for e in self.records if e['event']=='reference' and e['zone']=='C']
        self.assertEqual(actions, ['start','ready','start','reset'])
        self.assertTrue(any(e['event']=='zone_state' and e['new']=='LECTURER' for e in self.records))

    def test_pairing_recovery_does_not_log_an_operator_calibration_restart(self):
        self.server.fusion.calibrate(0)
        self.server.reference_operation('start', 'C', 0)
        self.server._evaluate_fusion(0)  # Offline -> raw UNKNOWN.
        self.now = .5
        for node in (1,3):
            self.send(1, node, payload=p.Telemetry(audio_window_seq=1,
                audio=(p.AudioWindow(640,p.AudioClass.UNKNOWN,(5,85,5,5)),)))
        self.server._evaluate_fusion(self.now)  # Raw CALIBRATING resumes, same revision.
        starts = [e for e in self.records if e['event']=='reference' and e['zone']=='C' and e['action']=='start']
        self.assertEqual(len(starts),1)


class EndToEnd(unittest.TestCase):
    def test_simulator_udp_csv_events_evaluate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (root/'run.csv').open('w+', newline='') as csv_file, (root/'run.jsonl').open('w+') as events_file:
                node_sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
                self.addCleanup(node_sock.close)
                node_sock.bind(('127.0.0.1',0))
                server = GatewayServer(('127.0.0.1',0), config_port=node_sock.getsockname()[1],
                    ping_interval=.2, csv_file=csv_file, events_file=events_file, out=io.StringIO(),
                    fusion=FusionEngine(FusionConfig(zones={1:'A',2:'B'})))
                self.addCleanup(server.close)
                sim = Simulator(2, seed=2, receive_jitter_s=0)  # Jitter reorders TELEMETRY behind PONGs: counted as loss
                # Run until every node has a report interval (random start phases), capped.
                stop = time.monotonic() + 8
                telemetry = Counter()
                server.telemetry_listeners.append(lambda header, *_: telemetry.update([header.node_id]))
                while time.monotonic() < stop and min(telemetry[1], telemetry[2]) < 3:
                    now = time.monotonic()
                    for _, data in sim.poll(now):
                        node_sock.sendto(data, server.sock.getsockname())
                    server.poll(.01)
                    while select.select([node_sock],[],[],0)[0]:
                        data, source = node_sock.recvfrom(p.MAX_DATAGRAM)
                        for reply in sim.handle(data, time.monotonic()):
                            node_sock.sendto(reply, source)
                for _ in range(10):
                    server.poll(0)
                server.close()
            result = evaluate(root/'run.csv', root/'run.jsonl')
            for node in (1,2):
                live = server.gateway.nodes[node]
                actual = result['nodes'][str(node)]
                for key in ('received','lost','duplicates','reboots'):
                    self.assertEqual(actual['packets'][key], getattr(live,key))
                self.assertGreater(actual['rtt_ms']['n'],0)
                self.assertGreater(actual['interval_ms']['n'],0)
            self.assertEqual(result['overall']['packets']['lost'],0)
            self.assertIn('zone:A:activity',result['fusion'])
            self.assertEqual(result['events']['counts']['run_end'],1)
            self.assertIn('Report timing',markdown(result))
