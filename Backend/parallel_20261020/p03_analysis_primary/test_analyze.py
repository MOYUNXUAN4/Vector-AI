import unittest
from analyze import join_active, latest_same_context, native_onset, number


class SourceTimingTests(unittest.TestCase):
    def row(self, layer='2', seq='4', t='100'):
        return dict(run_id='r',sequence=seq,platform_level=layer,geometry_platform_instance_id='-2',
                    geometry_version_id='-2-g1',source_timestamp=t,fall_event_backend_timestamp='101',_csv_line=2)

    def event(self, layer='2'):
        return dict(run_id='r',channel='purple',state='ACTIVE',line=1,
                    fields=dict(input_sequence='4',layer=layer,platform='-2',version='-2-g1'))

    def test_old_layer_does_not_warn_new_fall(self):
        old=self.row('1')
        self.assertIsNone(latest_same_context([self.event('1')],'purple',[old],self.row()))

    def test_exact_identity_and_clock_required(self):
        r=self.row()
        self.assertIsNotNone(join_active(self.event(),[r]))
        self.assertIsNone(join_active(self.event(),[r,r]))
        e=self.event();e['fields']['version']='old'
        self.assertIsNone(join_active(e,[r]))
        e=self.event();del e['fields']['input_sequence']
        self.assertIsNone(join_active(e,[r]))

    def test_no_missing_time_subtraction(self):
        a=self.row(t='');a['edge_warning_state']='False'
        b=self.row(seq='5');b['edge_warning_state']='True'
        self.assertIsNone(native_onset([a,b],b,'edge_warning_state'))
        self.assertIsNone(number('NaN'))
        self.assertIsNone(number(True))


if __name__=='__main__':unittest.main()
