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

"""Tasks around IBMi VM changes."""

import logging

from pypowervm import i18n
import pypowervm.tasks.scsi_mapper as pvm_smap
import pypowervm.tasks.vfc_mapper as pvm_vfcmap
import pypowervm.wrappers.base_partition as pvm_bp
import pypowervm.wrappers.logical_partition as pvm_lpar
from pypowervm.wrappers import virtual_io_server as pvm_vios

LOG = logging.getLogger(__name__)

# TODO(IBM) translation
_LE = i18n._


def update_load_src(adapter, lpar_w, boot_type):
    """Update load source of IBMi VM.

    Load source of IBMi vm will be set to the virtual adapter to which
    the boot volume is attached.
    :param adapter: The pypowervm adapter.
    :param lpar_w: The lpar wrapper.
    :param boot_type: The boot connectivity type of the VM.
    Possible value could be vscsi, npiv.
    :return: The updated LPAR wrapper. The update is not
    executed against the system, but rather the wrapper
    itself is updated locally.
    """
    load_source = None
    alt_load_source = None
    client_adapters = []
    if boot_type == 'npiv':
        msg = _LE("Setting Virtual Fiber Channel slot as "
                  "load source for VM %s") % lpar_w.name
        LOG.info(msg)
        vios_wraps = pvm_vios.VIOS.wrap(adapter.read(
            pvm_vios.VIOS.schema_type,
            xag=[pvm_vios.VIOS.xags.FC_MAPPING]))
        for vios_wrap in vios_wraps:
            existing_maps = pvm_vfcmap.find_maps(
                vios_wrap.vfc_mappings, lpar_w.id)
            client_adapters.extend([vfcmap.client_adapter
                                    for vfcmap in existing_maps])
    else:
        # That boot volume, which is vscsi physical volume, ssp lu
        # and local disk, could be handled here.
        msg = _LE("Setting Virtual SCSI slot slot as load "
                  "source for VM %s") % lpar_w.name
        LOG.info(msg)
        vios_wraps = pvm_vios.VIOS.wrap(adapter.read(
            pvm_vios.VIOS.schema_type,
            xag=[pvm_vios.VIOS.xags.SCSI_MAPPING]))
        for vios_wrap in vios_wraps:
            existing_maps = pvm_smap.find_maps(
                vios_wrap.scsi_mappings, lpar_w.id)
            client_adapters.extend([smap.client_adapter
                                    for smap in existing_maps])
    slot_nums = set(s.slot_number for s in client_adapters)
    slot_nums = list(slot_nums)
    slot_nums.sort()
    if len(slot_nums) > 0:
        load_source = slot_nums.pop(0)
    if len(slot_nums) > 0:
        alt_load_source = slot_nums.pop(0)
    if load_source is not None:
        if alt_load_source is None:
            alt_load_source = load_source
        lpar_w.io_config.tagged_io = pvm_bp.TaggedIO.bld(
            adapter, load_src=load_source,
            console='HMC',
            alt_load_src=alt_load_source)
    else:
        msg = _LE("No load source found for "
                  "VM %s") % lpar_w.name
        LOG.error(msg)
    lpar_w.desig_ipl_src = pvm_lpar.IPLSrc.B
    lpar_w.keylock_pos = pvm_bp.KeylockPos.NORMAL
    return lpar_w
