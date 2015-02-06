# Copyright 2015 IBM Corp.
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

import logging

import pypowervm.util as u
import pypowervm.wrappers.constants as c
import pypowervm.wrappers.entry_wrapper as ewrap
import pypowervm.wrappers.managed_system as ms
import pypowervm.wrappers.storage as stor

LOG = logging.getLogger(__name__)

# Cluster Constants
CL_NAME = 'ClusterName'
CL_ID = 'ClusterID'
CL_REPOPVS = 'RepositoryDisk'  # Yes, really
CL_PV = c.PV
CL_SSP_LINK = 'ClusterSharedStoragePool'
CL_NODES = 'Node'  # Yes, really
CL_NODE = 'Node'

# Shared Storage Pool Constants
SSP_NAME = 'StoragePoolName'
SSP_UDID = c.UDID
SSP_CAPACITY = 'Capacity'
SSP_FREE_SPACE = 'FreeSpace'
SSP_TOTAL_LU_SIZE = 'TotalLogicalUnitSize'
SSP_LUS = 'LogicalUnits'
SSP_LU = 'LogicalUnit'
SSP_PVS = c.PVS
SSP_PV = c.PV

# Node Constants
N_HOSTNAME = 'HostName'
N_LPARID = 'PartitionID'
N_VIOS_LINK = c.VIOS
N_MTMS = 'MachineTypeModelAndSerialNumber'


class Cluster(ewrap.EntryWrapper):
    """A Cluster behind a SharedStoragePool."""

    @property
    def name(self):
        return self.get_parm_value(CL_NAME)

    @property
    def id(self):
        """The string ID according to VIOS, not a UUID or UDID."""
        return self.get_parm_value(CL_ID)

    @property
    def ssp_uri(self):
        """The URI of the SharedStoragePool associated with this Cluster."""
        el = self.get_href(CL_SSP_LINK)
        if el:
            return el[0]
        return None

    @property
    def ssp_uuid(self):
        """The UUID of the SharedStoragePool associated with this Cluster."""
        uri = self.ssp_uri
        if uri is not None:
            return u.get_req_path_uuid(uri)

    @property
    def repos_pvs(self):
        """WrapperElemList of PhysicalVolume wrappers."""
        return ewrap.WrapperElemList(self._find_or_seed(CL_REPOPVS),
                                     CL_PV, stor.PhysicalVolume)

    @repos_pvs.setter
    def repos_pvs(self, pvs):
        self.replace_list(CL_REPOPVS, pvs)

    @property
    def nodes(self):
        """WrapperElemList of Node wrappers."""
        return ewrap.WrapperElemList(self._find_or_seed(CL_NODES),
                                     CL_NODE, Node)

    @nodes.setter
    def nodes(self, ns):
        self.replace_list(CL_NODES, ns)


class SharedStoragePool(ewrap.EntryWrapper):
    """A Shared Storage Pool containing PVs and LUs."""

    @property
    def name(self):
        return self.get_parm_value(SSP_NAME)

    @property
    def udid(self):
        return self.get_parm_value(SSP_UDID)

    @property
    def capacity(self):
        """Float capacity in GB."""
        return float(self.get_parm_value(SSP_CAPACITY))

    @property
    def free_space(self):
        """Float free space in GB."""
        return float(self.get_parm_value(SSP_FREE_SPACE))

    @property
    def total_lu_size(self):
        """Float total LU size in GB."""
        return float(self.get_parm_value(SSP_TOTAL_LU_SIZE))

    @property
    def logical_units(self):
        """WrapperElemList of LogicalUnit wrappers."""
        return ewrap.WrapperElemList(self._find_or_seed(SSP_LUS),
                                     SSP_LU, stor.LogicalUnit)

    @logical_units.setter
    def logical_units(self, lus):
        self.replace_list(SSP_LUS, lus)

    @property
    def physical_volumes(self):
        """WrapperElemList of PhysicalVolume wrappers."""
        return ewrap.WrapperElemList(self._find_or_seed(SSP_PVS),
                                     SSP_PV, stor.PhysicalVolume)

    @physical_volumes.setter
    def physical_volumes(self, pvs):
        self.replace_list(SSP_PVS, pvs)


class Node(ewrap.ElementWrapper):

    @property
    def hostname(self):
        return self.get_parm_value(N_HOSTNAME)

    @property
    def lparid(self):
        """Small integer partition ID, not UUID."""
        return self.get_parm_value_int(N_LPARID)

    @property
    def mtms(self):
        """MTMS Element wrapper of the system hosting the Node (VIOS)."""
        return ms.MTMS(self._find(N_MTMS))

    @property
    def vios_uri(self):
        """The URI of the VIOS.

        This is only set if the VIOS is on this system!
        """
        el = self.get_href(N_VIOS_LINK)
        if el:
            return el[0]
        return None

    @property
    def vios_uuid(self):
        """The UUID of the Node (VIOS).

        This is only set if the VIOS is on this system!
        """
        uri = self.vios_uri
        if uri is not None:
            return u.get_req_path_uuid(uri)
