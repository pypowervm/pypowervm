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

# Node Constants
N_HOSTNAME = 'HostName'
N_LPARID = 'PartitionID'
N_VIOS_LINK = c.VIOS
N_MTMS = 'MachineTypeModelAndSerialNumber'


class Clust(ewrap.EntryWrapper):
    """A Cluster behind a SharedStoragePool."""

    schema_type = c.CLUSTER
    has_metadata = True

    @classmethod
    def new(cls, name=None, repos_pv=None, node_list=()):
        """Create a fresh Clust EntryWrapper.

        :param name: String name for the Cluster.
        :param repos_pv: storage.PV representing the repository disk.
        :param node_list: Iterable of Node wrappers representing the VIOS(es)
        to host the Cluster.  Each VIOS must be able to see each disk.  Note
        that this must contain exactly one Node if this Clust wrapper is to
        be used to create a new Cluster/SharedStoragePool pair.
        """
        # The order of these assignments IS significant.
        cluster = cls()
        if name:
            cluster.name = name
        if repos_pv:
            cluster.repos_pv = repos_pv
        if node_list:
            cluster.nodes = node_list
        return cluster

    @property
    def name(self):
        return self._get_val_str(CL_NAME)

    @name.setter
    def name(self, newname):
        self.set_parm_value(CL_NAME, newname)

    @property
    def id(self):
        """The string ID according to VIOS, not a UUID or UDID."""
        return self._get_val_str(CL_ID)

    @property
    def ssp_uri(self):
        """The URI of the SharedStoragePool associated with this Cluster."""
        return self.get_href(CL_SSP_LINK, one_result=True)

    @property
    def ssp_uuid(self):
        """The UUID of the SharedStoragePool associated with this Cluster."""
        uri = self.ssp_uri
        if uri is not None:
            return u.get_req_path_uuid(uri)

    @property
    def repos_pv(self):
        """Returns the (one) repository PV.

        Although the schema technically allows a collection of PVs under the
        RepositoryDisk element, a Cluster always has exactly one repository PV.
        """
        repos_elem = self._find_or_seed(CL_REPOPVS)
        pv_list = repos_elem.findall(CL_PV)
        # Check only relevant when building up a Clust wrapper internally
        if pv_list and len(pv_list) == 1:
            return stor.PV(pv_list[0])
        return None

    @repos_pv.setter
    def repos_pv(self, pv):
        """Set the (single) PV member of RepositoryDisk.

        You cannot change the repository disk of a live Cluster.  This setter
        is useful only when constructing new Clusters.

        :param pv: The PV (NOT a list) to set.
        """
        self.replace_list(CL_REPOPVS, [pv])

    @property
    def nodes(self):
        """WrapperElemList of Node wrappers."""
        return ewrap.WrapperElemList(self._find_or_seed(CL_NODES),
                                     CL_NODE, Node)

    @nodes.setter
    def nodes(self, ns):
        self.replace_list(CL_NODES, ns)


class Node(ewrap.ElementWrapper):
    """A Node represents a VIOS member of a Cluster.

    A Cluster cannot simply contain VirtualIOServer links because it is
    likely that some of the Cluster's members are not managed by the same
    instance of the PowerVM REST server, which would then have no way to
    construct said links.  In such cases, the Node object supplies enough
    information about the VIOS that it could be found by a determined consumer.

    To add a new Node to a Cluster, only the hostname is required.
    n = Node()
    n.hostname = ...
    cluster.nodes.append(n)
    adapter.update(...)
    """

    schema_type = c.CLUST_NODE
    has_metadata = True

    @classmethod
    def new(cls, hostname=None, lpar_id=None, mtms=None, vios_uri=None):
        """Create a fresh Node ElementWrapper.

        :param hostname: String hostname (or IP) of the Node.
        :param lpar_id: Integer LPAR ID of the Node.
        :param mtms: String OR managed_system.MTMS wrapper representing the
                     Machine Type, Model, and Serial Number of the system
                     hosting the VIOS.  String format: 'MT-M*S'
                     e.g. '8247-22L*1234A0B'.
        :param vios_uri: String URI representing this Node.
        """
        # The order of these assignments IS significant
        node = cls()
        if hostname:
            node.hostname = hostname
        if lpar_id:
            node.lpar_id = lpar_id
        if mtms:
            node.mtms = mtms
        if vios_uri:
            node.vios_uri = vios_uri

        return node

    @property
    def hostname(self):
        return self._get_val_str(N_HOSTNAME)

    @hostname.setter
    def hostname(self, hn):
        self.set_parm_value(N_HOSTNAME, hn)

    @property
    def lpar_id(self):
        """Small integer partition ID, not UUID."""
        return self._get_val_int(N_LPARID)

    @lpar_id.setter
    def lpar_id(self, new_lpar_id):
        self.set_parm_value(N_LPARID, str(new_lpar_id))

    @property
    def mtms(self):
        """MTMS Element wrapper of the system hosting the Node (VIOS)."""
        return ms.MTMS(self._find(N_MTMS))

    @mtms.setter
    def mtms(self, new_mtms):
        """Sets the MTMS of the Node.

        :param new_mtms: May be either a string of the form 'MT-M*S' or a
                         managed_system.MTMS ElementWrapper.
        """
        el = self._find_or_seed(N_MTMS)
        if not isinstance(new_mtms, ms.MTMS):
            new_mtms = ms.MTMS.new(new_mtms)
        self._element.replace(el, new_mtms._element)

    @property
    def vios_uri(self):
        """The URI of the VIOS.

        This is only set if the VIOS is on this system!
        """
        return self.get_href(N_VIOS_LINK, one_result=True)

    @vios_uri.setter
    def vios_uri(self, new_uri):
        self.set_href(N_VIOS_LINK, new_uri)

    @property
    def vios_uuid(self):
        """The UUID of the Node (VIOS).

        This is only set if the VIOS is on this system!
        """
        uri = self.vios_uri
        if uri is not None:
            return u.get_req_path_uuid(uri)
