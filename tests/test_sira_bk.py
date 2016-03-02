__author__ = 'sudipta'

import unittest
import cPickle
import os
import numpy as np

from sifra.sifra_bk import calc_loss_arrays as calc_loss_arrays_bk
from sifra.sifra import calc_loss_arrays
from sifra.sifraclasses import ScenarioDataGetter, Facility, Scenario
from sifra.sifra import power_calc


class TestSiraBk(unittest.TestCase):

    def test_calc_loss_arrays(self):
        sc = ScenarioDataGetter('tests/config_ps_X_test.conf')
        facility = Facility('tests/config_ps_X_test.conf')
        """
        :return: tests the calc_loss_arrays function, which is the main.
        """
        print '======================Testing serial run ============================='
        ids_comp_vs_haz, sys_output_dict, component_resp_dict = calc_loss_arrays_bk(parallel_or_serial=0)
        test_ids_comp_vs_haz = cPickle.load(open('tests/ids_comp_vs_haz.pick', 'rb'))
        test_sys_output_dict = cPickle.load(open('tests/sys_output_dict.pick', 'rb'))
        for k, v in ids_comp_vs_haz.iteritems():
            self.assertEqual(v.shape, (sc.num_samples, facility.num_elements))

        for k in ids_comp_vs_haz:
            np.testing.assert_array_equal(ids_comp_vs_haz[k], test_ids_comp_vs_haz[k], 'arrays not equal', verbose=True)

        for k in sys_output_dict:
            np.testing.assert_array_equal(sys_output_dict[k], test_sys_output_dict[k], 'arrays not equal', verbose=True)

    def test_calc_loss_arrays_parallel(self):
        """
        :return: tests the calc_loss_arrays function, which is the main.
        """
        sc = Scenario('tests/config_ps_X_test.conf')
        facility = Facility('tests/config_ps_X_test.conf')
        print '\n\n======================Testing parallel run ============================='
        ids_comp_vs_haz, sys_output_dict, component_resp_dict = calc_loss_arrays_bk(parallel_or_serial=1)
        test_ids_comp_vs_haz = cPickle.load(open('tests/ids_comp_vs_haz.pick', 'rb'))
        test_sys_output_dict = cPickle.load(open('tests/sys_output_dict.pick', 'rb'))
        for k, v in ids_comp_vs_haz.iteritems():
            self.assertEqual(v.shape, (sc.num_samples, facility.num_elements))

        for k in ids_comp_vs_haz:
            np.testing.assert_array_equal(ids_comp_vs_haz[k], test_ids_comp_vs_haz[k], 'arrays not equal', verbose=True)

        for k in sys_output_dict:
            np.testing.assert_array_equal(sys_output_dict[k], test_sys_output_dict[k], 'arrays not equal', verbose=True)


if __name__ == '__main__':
    unittest.main()