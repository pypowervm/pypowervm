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

"""Wrappers, constants, and helpers around ManagementConsole."""

import pypowervm.const as c
import pypowervm.util as u
import pypowervm.wrappers.entry_wrapper as ewrap

import logging

LOG = logging.getLogger(__name__)

_MGMT_CON_NAME = 'ManagementConsoleName'

# MTMS XPath constants
_MTMS_ROOT = 'MachineTypeModelAndSerialNumber'
_MTMS_MT = 'MachineType'
_MTMS_MODEL = 'Model'
_MTMS_SERIAL = 'SerialNumber'

_MGND_SYS_LINK = u.xpath("ManagedSystems", c.LINK)

# NETI XPath constants
_NETI_ROOT = 'NetworkInterfaces'

_MGMT_NETI_ROOT = 'ManagementConsoleNetworkInterface'
_MGMT_NETI_NAME = 'InterfaceName'
_MGMT_NETI_ADDRESS = 'NetworkAddress'

# SSH Config
_PUB_KEY = 'PublicSSHKey'
_AUTH_KEYS = 'AuthorizedKeys'


@ewrap.EntryWrapper.pvm_type('ManagementConsole')
class Console(ewrap.EntryWrapper):

    @property
    def name(self):
        return self._get_val_str(_MGMT_CON_NAME)

    @property
    def mtms(self):
        return MTMS.wrap(self.element.find(_MTMS_ROOT))

    @property
    def mgnd_sys_links(self):
        """List of hrefs from ManagedSystems.

        This is a READ-ONLY list.
        """
        return self.get_href(_MGND_SYS_LINK)

    @property
    def network_infaces(self):
        return NetworkInterfaces.wrap(self.element.find(_NETI_ROOT))

    @property
    def ssh_public_key(self):
        return self._get_val_str(_PUB_KEY)

    @property
    def ssh_authorized_keys(self):
        return tuple(self._get_vals(_AUTH_KEYS))


@ewrap.ElementWrapper.pvm_type(_MTMS_ROOT, has_metadata=True)
class MTMS(ewrap.ElementWrapper):
    """The Machine Type, Model and Serial Number wrapper."""

    @property
    def machine_type(self):
        return self._get_val_str(_MTMS_MT)

    @property
    def model(self):
        return self._get_val_str(_MTMS_MODEL)

    @property
    def serial(self):
        return self._get_val_str(_MTMS_SERIAL)


@ewrap.ElementWrapper.pvm_type(_NETI_ROOT, has_metadata=True)
class NetworkInterfaces(ewrap.ElementWrapper):
    """The Network Interfaces wrapper."""

    @property
    def console_interface(self):
        return ConsoleNetworkInterfaces.wrap(
            self.element.find(_MGMT_NETI_ROOT))


@ewrap.ElementWrapper.pvm_type(_MGMT_NETI_ROOT, has_metadata=True)
class ConsoleNetworkInterfaces(ewrap.ElementWrapper):
    """The Console Network Interfaces wrapper."""

    @property
    def name(self):
        return self._get_val_str(_MGMT_NETI_NAME)

    @property
    def address(self):
        return self._get_val_str(_MGMT_NETI_ADDRESS)
