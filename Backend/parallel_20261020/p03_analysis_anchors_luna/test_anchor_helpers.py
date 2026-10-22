"""Small boundary tests for the read-only anchor eligibility helpers."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_p03_anchors as audit


def row(seq, source_time='100.0', q=1.0, flag='true'):
    return {'sequence':str(seq),'source_timestamp':source_time,
            'directional_edge_distance':str(q+1),'ball_radius':'0.5',
            'directional_edge_valid':flag,'geometry_query_valid':'true',
            'geometry_ownership_valid':'true','run_id':'r','layer_id':'2',
            'geometry_platform_instance_id':'p','geometry_version_id':'v'}


class AnchorHelperTests(unittest.TestCase):
    def test_valid_adjacent_bracket(self):
        result=audit.eligible_crossing(row(1,'100.0',1),row(2,'100.05',0))
        self.assertAlmostEqual(result['bracket_source_dt_s'],0.05)

    def test_missing_or_nonfinite_source_time_blocks_bracket(self):
        self.assertIsNone(audit.eligible_crossing(row(1,None,1),row(2,'100.05',0)))
        self.assertIsNone(audit.eligible_crossing(row(1,'nan',1),row(2,'100.05',0)))

    def test_missing_or_false_geometry_flag_blocks_bracket(self):
        a=row(1,'100.0',1); del a['geometry_query_valid']
        self.assertIsNone(audit.eligible_crossing(a,row(2,'100.05',0)))
        self.assertIsNone(audit.eligible_crossing(row(1,'100.0',1,'false'),row(2,'100.05',0)))

    def test_invalid_identity_sequence_or_gap_blocks_bracket(self):
        c=row(3,'100.05',0)
        self.assertIsNone(audit.eligible_crossing(row(1,'100.0',1),c))
        c=row(2,'100.2',0)
        self.assertIsNone(audit.eligible_crossing(row(1,'100.0',1),c))
        c=row(2,'100.05',0); c['geometry_version_id']='new'
        self.assertIsNone(audit.eligible_crossing(row(1,'100.0',1),c))

    def test_fall_anchor_requires_flag_and_positive_finite_timestamp(self):
        self.assertTrue(audit.valid_fall_anchor({'fall_event':'true','fall_event_backend_timestamp':'100.2'}))
        for flag,ts in [('false','100.2'),('true',''),('true','nan'),('true','0'),('true','-1')]:
            self.assertFalse(audit.valid_fall_anchor({'fall_event':flag,'fall_event_backend_timestamp':ts}))

    def test_wii_field_counts_separate_missing_false_and_true(self):
        stats=audit.wii_partition_stats([
            {'wii_board_loaded':'true','wii_center_applied':'false','wii_control_valid':''},
            {'wii_board_loaded':'','wii_center_applied':'true','wii_control_valid':'false'}])
        self.assertEqual(stats['field_counts']['wii_board_loaded'],{'present':1,'true':1,'false':0,'missing':1})
        self.assertEqual(stats['field_counts']['wii_center_applied'],{'present':2,'true':1,'false':1,'missing':0})
        self.assertEqual(stats['field_counts']['wii_control_valid'],{'present':1,'true':0,'false':1,'missing':1})


if __name__=='__main__': unittest.main()
