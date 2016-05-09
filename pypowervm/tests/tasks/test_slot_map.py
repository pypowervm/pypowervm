# Copyright 2016 IBM Corp.
#
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""Test pypowervm.tasks.slot_map."""

import mock
import testtools

from pypowervm.tasks import slot_map
from pypowervm.tests.test_utils import pvmhttp
from pypowervm.wrappers import network as net
from pypowervm.wrappers import virtual_io_server as vios


def loadf(wcls, fname):
    return wcls.wrap(pvmhttp.load_pvm_resp(fname).get_response())

# Load data files just once, since the wrappers will be read-only
vio1 = loadf(vios.VIOS, 'fake_vios_ssp_npiv.txt')
vio2 = loadf(vios.VIOS, 'fake_vios_mappings.txt')
cnafeed1 = loadf(net.CNA, 'cna_feed1.txt')
vswitchfeed = loadf(net.VSwitch, 'vswitch_feed.txt')


class SlotMapTestImpl(slot_map.SlotMapBase):

    def __init__(self, inst_key, load=True, load_ret=None):
        self._load_ret = load_ret
        self.load_calls = 0
        super(SlotMapTestImpl, self).__init__(inst_key, load=load)

    def set_load_ret(self, val):
        self._load_ret = val

    def load(self):
        self.load_calls += 1
        return self._load_ret

    def save(self):
        pass

    def delete(self):
        pass


class TestSlotMapBase(testtools.TestCase):
    """Test slot_map.SlotMapBase."""

    def test_ioclass_consts(self):
        """Make sure the IOCLASS constants are disparate."""
        constl = [key for key in dir(slot_map.IOCLASS) if not
                  key.startswith('_')]
        self.assertEqual(len(constl), len(set(constl)))

    def test_init_calls_load(self):
        """Ensure SlotMapBase.__init__ calls load or not based on the param."""
        loads = SlotMapTestImpl('foo')
        self.assertEqual(1, loads.load_calls)
        self.assertEqual('foo', loads.inst_key)
        doesnt_load = SlotMapTestImpl('bar', load=False)
        self.assertEqual(0, doesnt_load.load_calls)

    @mock.patch('pickle.loads')
    def test_init_deserialize(self, mock_unpickle):
        """Ensure __init__ deserializes or not based on what's loaded."""
        # By default, load returns None, so nothing to unpickle
        doesnt_unpickle = SlotMapTestImpl('foo')
        mock_unpickle.assert_not_called()
        self.assertEqual({}, doesnt_unpickle.topology)
        unpickles = SlotMapTestImpl('foo', load_ret='abc123')
        mock_unpickle.assert_called_once_with('abc123')
        self.assertEqual(mock_unpickle.return_value, unpickles.topology)

    @mock.patch('pickle.dumps')
    @mock.patch('pypowervm.tasks.slot_map.SlotMapBase.topology',
                new_callable=mock.PropertyMock)
    def test_str_serialize(self, mock_topo, mock_pickle):
        """Ensure str serializes the topology."""
        mock_pickle.return_value = 'abc123'
        smt = SlotMapTestImpl('foo')
        self.assertEqual('abc123', str(smt))
        mock_pickle.assert_called_once_with(mock_topo.return_value)
        mock_topo.assert_called_once()

    @mock.patch('pypowervm.wrappers.managed_system.System.get')
    @mock.patch('pypowervm.wrappers.network.VSwitch.get')
    def test_vswitch_id2name(self, mock_vsw_get, mock_sys_get):
        """Ensure _vswitch_id2name caches, and gets the right content."""
        mock_vsw_get.return_value = vswitchfeed
        mock_sys_get.return_value = ['sys']
        smt = SlotMapTestImpl('foo')
        # We didn't cache yet
        mock_vsw_get.assert_not_called()
        mock_sys_get.assert_not_called()
        map1 = smt._vswitch_id2name('adap')
        # Now we grabbed the REST data
        mock_vsw_get.assert_called_once_with('adap', parent='sys')
        mock_sys_get.assert_called_once_with('adap')

        mock_vsw_get.reset_mock()
        mock_sys_get.reset_mock()
        map2 = smt._vswitch_id2name('adap2')
        # The same data is returned each time
        self.assertEqual(map2, map1)
        # The second call didn't re-fetch from REST
        mock_vsw_get.assert_not_called()
        mock_sys_get.assert_not_called()
        # Make sure the data is in the right shape
        self.assertEqual({0: 'ETHERNET0', 1: 'MGMTSWITCH'}, map1)

    @mock.patch('pypowervm.wrappers.managed_system.System.get')
    @mock.patch('pypowervm.wrappers.network.VSwitch.get')
    def test_register_cna(self, mock_vsw_get, mock_sys_get):
        """Test register_cna."""
        mock_vsw_get.return_value = vswitchfeed
        mock_sys_get.return_value = ['sys']
        smt = SlotMapTestImpl('foo')
        for cna in cnafeed1:
            smt.register_cna(cna)
        self.assertEqual({3: {'CNA': {'5E372CFD9E6D': 'ETHERNET0'}},
                          4: {'CNA': {'2A2E57A4DE9C': 'ETHERNET0'}},
                          6: {'CNA': {'3AEAC528A7E3': 'MGMTSWITCH'}}},
                         smt.topology)

    def test_register_vfc_mapping(self):
        """Test register_vfc_mapping."""
        smt = SlotMapTestImpl('foo')
        i = 1
        for vio in (vio1, vio2):
            for vfcmap in vio.vfc_mappings:
                smt.register_vfc_mapping(vfcmap, 'fab%d' % i)
                i += 1
        self.assertEqual({3: {'VFC': {'fab1': None, 'fab10': None,
                                      'fab11': None, 'fab12': None,
                                      'fab13': None, 'fab14': None,
                                      'fab15': None, 'fab16': None,
                                      'fab17': None, 'fab18': None,
                                      'fab19': None, 'fab20': None,
                                      'fab21': None, 'fab22': None,
                                      'fab23': None, 'fab24': None,
                                      'fab25': None, 'fab26': None,
                                      'fab28': None, 'fab29': None,
                                      'fab3': None, 'fab30': None,
                                      'fab31': None, 'fab32': None,
                                      'fab33': None, 'fab4': None,
                                      'fab5': None, 'fab6': None,
                                      'fab7': None, 'fab8': None,
                                      'fab9': None}},
                          6: {'VFC': {'fab2': None}},
                          8: {'VFC': {'fab27': None}}}, smt.topology)

    def test_register_vscsi_mappings(self):
        """Test register_vscsi_mappings."""
        smt = SlotMapTestImpl('foo')
        for vio in (vio1, vio2):
            for vscsimap in vio.scsi_mappings:
                smt.register_vscsi_mapping(vscsimap)
        self.assertEqual(
            {2: {'LU': {'274d7bb790666211e3bc1a00006cae8b013842794fa0b8e9dd771'
                        'd6a32accde003': None,
                        '274d7bb790666211e3bc1a00006cae8b0148326cf1e5542c583ec'
                        '14327771522b0': None,
                        '274d7bb790666211e3bc1a00006cae8b01ac18997ab9bc23fb247'
                        '56e9713a93f90': None,
                        '274d7bb790666211e3bc1a00006cae8b01c96f590914bccbc8b7b'
                        '88c37165c0485': None},
                 'PV': {'01M0lCTTIxNDUzMTI2MDA1MDc2ODAyODIwQTlEQTgwMDAwMDAwMDA'
                        'wNTJBOQ==': None},
                 'VDisk': {'0300004c7a00007a00000001466c54110f.16': 0.125},
                 'VOptMedia': {'VOptMedia': None}},
             3: {'VDisk': {'0300025d4a00007a000000014b36d9deaf.1': 60.0}}},
            smt.topology)