import csv
import json
import socket
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from timesync_logger import TimeSynchronizedLogger, WII_CONTROL_FIELDS
from udp_packet_reader import recv_json_packet


class WiiControlLoggerTests(unittest.TestCase):
    def read(self, logger):
        logger.close()
        with open(logger.path, newline='', encoding='utf-8') as f:
            reader=csv.DictReader(f);rows=list(reader);return reader.fieldnames,rows

    def test_legacy_and_non_wii_do_not_invent_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger=TimeSynchronizedLogger('test',tmp)
            logger.record('wii', {'cop_x':.2}, sequence=1)
            logger.record('unity', {k:True for k in WII_CONTROL_FIELDS}, sequence=1)
            logger.record('game', {k:True for k in WII_CONTROL_FIELDS}, sequence=1)
            fields,rows=self.read(logger)
        self.assertEqual(fields[-len(WII_CONTROL_FIELDS):],list(WII_CONTROL_FIELDS))
        self.assertEqual(len(fields),len(set(fields)))
        for row in rows:self.assertTrue(all(row[k]=='' for k in WII_CONTROL_FIELDS))

    def test_false_zero_and_unknown_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger=TimeSynchronizedLogger('test',tmp)
            logger.record('wii',{'wii_control_valid':False,'wii_issued_left':False,
                'wii_center_generation':0,'wii_center_offset_tl':0.0,'wii_issued_right':None},sequence=1)
            _,rows=self.read(logger)
        self.assertEqual(rows[0]['wii_control_valid'],'False')
        self.assertEqual(rows[0]['wii_issued_left'],'False')
        self.assertEqual(rows[0]['wii_center_generation'],'0')
        self.assertEqual(rows[0]['wii_center_offset_tl'],'0.0')
        self.assertEqual(rows[0]['wii_issued_right'],'')

    def test_optional_malformed_value_retained_not_used_as_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger=TimeSynchronizedLogger('test',tmp)
            logger.record('wii',{'wii_control_age_seconds':'not-a-number','wii_control_valid':'invalid'},sequence=1)
            _,rows=self.read(logger)
        self.assertEqual(rows[0]['wii_control_age_seconds'],'not-a-number')
        self.assertEqual(rows[0]['wii_control_valid'],'invalid')

    def test_loopback_new_and_old_packets_to_new_csv(self):
        payload={'type':'wii_balance','timestamp':'2026-10-14T03:00:00Z','sequence':12,
            'wii_control_schema':'wii_control_v1','wii_controller_instance_id':'sender-a',
            'wii_control_sequence':7,'wii_control_timestamp':'2026-10-14T02:59:59.980Z',
            'wii_control_valid':True,'wii_control_age_seconds':.020,
            'wii_control_raw_cop_not_one_to_one':True,'wii_actions_enabled':True,
            'wii_issued_left':True,'wii_issued_right':False,'wii_key_left':'A',
            'wii_center_generation':2,'wii_center_applied':True,'wii_center_offset_tl':.3}
        with tempfile.TemporaryDirectory() as tmp:
            logger=TimeSynchronizedLogger('test',tmp)
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as rx,socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as tx:
                rx.bind(('127.0.0.1',0));rx.settimeout(2)
                for pkt in [payload,dict(payload,sequence=13,wii_control_age_seconds=.04),{'type':'wii_balance','sequence':14,'timestamp':payload['timestamp']}]:
                    tx.sendto(json.dumps(pkt).encode(),rx.getsockname());received=recv_json_packet(rx)
                    self.assertIsNotNone(received)
                    logger.record('wii',received.payload,source_timestamp=received.payload.get('timestamp'),sequence=received.payload['sequence'])
            fields,rows=self.read(logger)
        self.assertEqual(rows[0]['sequence'],'12');self.assertEqual(rows[0]['wii_control_sequence'],'7')
        self.assertEqual(rows[1]['sequence'],'13');self.assertEqual(rows[1]['wii_control_sequence'],'7')
        self.assertEqual(rows[0]['wii_issued_left'],'True');self.assertEqual(rows[0]['wii_issued_right'],'False')
        self.assertEqual(rows[0]['wii_control_timestamp'],payload['wii_control_timestamp'])
        self.assertEqual(rows[0]['source_timestamp'],payload['timestamp'])
        self.assertTrue(all(rows[2][k]=='' for k in WII_CONTROL_FIELDS))

if __name__=='__main__':unittest.main()
