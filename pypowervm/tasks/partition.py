# Copyright 2015, 2016 IBM Corp.
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

"""Tasks specific to partitions (LPARs and VIOSes)."""

from oslo_log import log as logging
import psutil
import time

import pypowervm.const as c
import pypowervm.exceptions as ex
from pypowervm.i18n import _
import pypowervm.util as u
import pypowervm.utils.transaction as tx
import pypowervm.wrappers.base_partition as bp
import pypowervm.wrappers.logical_partition as lpar
import pypowervm.wrappers.virtual_io_server as vios

LOG = logging.getLogger(__name__)

# RMC must be either active or busy.  Busy is allowed because that simply
# means that something is running against the VIOS at the moment...but
# it should recover shortly.
_VALID_RMC_STATES = (bp.RMCState.ACTIVE, bp.RMCState.BUSY)

# Only a running state is OK for now.
_VALID_VM_STATES = (bp.LPARState.RUNNING,)

# Not the opposite of the above
_DOWN_VM_STATES = (bp.LPARState.NOT_ACTIVATED, bp.LPARState.ERROR,
                   bp.LPARState.NOT_AVAILBLE, bp.LPARState.SHUTTING_DOWN,
                   bp.LPARState.SUSPENDED, bp.LPARState.SUSPENDING,
                   bp.LPARState.UNKNOWN)


def get_mgmt_partition(adapter):
    """Get the LPAR/VIOS wrapper representing the PowerVM management partition.

    :param adapter: The pypowervm.adapter.Adapter through which to query the
                    REST API.
    :return: pypowervm.wrappers.logical_partition.LPAR/virtual_io_server.VIOS
             wrapper representing the management partition.
    :raise ManagementPartitionNotFoundException: if we don't find exactly one
                                                 management partition.
    """

    # There will almost always be fewer VIOSes than LPARs.  Since we're
    # querying without xags, it should be very quick.
    vio_wraps = vios.VIOS.search(adapter, is_mgmt_partition=True)
    if len(vio_wraps) == 1:
        return vio_wraps[0]

    # We delay the query to the LPARs because there could be hundreds of them.
    # So we don't want to query it unless we need to.
    lpar_wraps = lpar.LPAR.search(adapter, is_mgmt_partition=True)
    if len(lpar_wraps) == 1:
        return lpar_wraps[0]

    # If we made it here, something is wrong.
    raise ex.ManagementPartitionNotFoundException(
        count=len(vio_wraps + lpar_wraps))


def get_this_partition(adapter):
    """Get the LPAR/VIOS wrapper of the node on which this method is running.

    :param adapter: The pypowervm.adapter.Adapter through which to query the
                    REST API.
    :return: pypowervm.wrappers.logical_partition.LPAR/virtual_io_server.VIOS
             wrapper representing the local partition.
    :raise LocalPartitionNotFoundException: if we don't find exactly one LPAR/
                                            VIOS with the local VM's short ID.
    """
    myid = u.my_partition_id()

    # There will almost always be fewer VIOSes than LPARs.  Since we're
    # querying without xags, it should be very quick.
    vio_wraps = vios.VIOS.search(adapter, id=myid)
    if len(vio_wraps) == 1:
        return vio_wraps[0]

    # We delay the query to the LPARs because there could be hundreds of them.
    # So we don't want to query it unless we need to.
    lpar_wraps = lpar.LPAR.search(adapter, id=myid)
    if len(lpar_wraps) == 1:
        return lpar_wraps[0]

    # If we made it here, something is wrong.
    raise ex.ThisPartitionNotFoundException(
        count=len(vio_wraps + lpar_wraps), lpar_id=myid)


def get_active_vioses(adapter, xag=(), vios_wraps=None, find_min=None):
    """Returns a list of active Virtual I/O Server Wrappers for a host.

    Active is defined by powered on and RMC state being 'active'.  The
    VIOSes will be sorted such that if the Mgmt partition is a VIOS, it is
    the first in the list.

    :param adapter: The pypowervm adapter for the query.
    :param xag: (Optional, Default: ()) Iterable of extended attributes to use.
    :param vios_wraps: (Optional, Default: None) A list of VIOS wrappers. If
                       specified, the method will check for active VIOSes
                       in this list instead of issuing a GET.
    :param find_min: (Optional, Default: None) If specified, the minimum
                     acceptable number of active VIOSes.  If fewer are found,
                     this method raises NotEnoughActiveVioses.
    :return: List of VIOS wrappers.
    :raise NotEnoughActiveVioses: If find_min is specified and the number of
                                  active VIOSes is less than the specified
                                  number.
    """
    if vios_wraps is None:
        vios_wraps = vios.VIOS.get(adapter, xag=xag)

    # A VIOS is 'active' if it is powered on and either RMC is active or it
    # is the mgmt partition.
    ret = [vio for vio in vios_wraps if vio.state in _VALID_VM_STATES and
           (vio.rmc_state in _VALID_RMC_STATES or vio.is_mgmt_partition)]
    ret = sorted(ret, key=lambda x: x.is_mgmt_partition, reverse=True)

    if find_min is not None and len(ret) < find_min:
        raise ex.NotEnoughActiveVioses(exp=find_min, act=len(ret))

    LOG.debug('Found active VIOS(es): %s', str([vio.name for vio in ret]))

    return ret


def get_partitions(adapter, lpars=True, vioses=True, mgmt=False):
    """Get a list of partitions.

    Can include LPARs, VIOSes, and the management partition.

    :param adapter: The pypowervm adapter.
    :param lpars: If True, the result will include all LPARs.
    :param vioses: If True, the result will include all VIOSes.
    :param mgmt: If True, the result is guaranteed to include the
                 management partition, even if it would not otherwise have
                 been included based on get_lpars/get_vioses.
    """
    rets = []
    if vioses:
        rets.extend(vios.VIOS.get(adapter))
    if lpars:
        rets.extend(lpar.LPAR.get(adapter))

    # If they need the mgmt lpar, get it.  But ONLY if we didn't get both
    # VIOSes and LPARs.  If we got both of those already, then we are
    # guaranteed to already have the mgmt lpar in there.
    if mgmt and not (lpars and vioses):
        mgmt_w = get_mgmt_partition(adapter)
        if mgmt_w.uuid not in [x.uuid for x in rets]:
            rets.append(get_mgmt_partition(adapter))

    return rets


def get_physical_wwpns(adapter):
    """Returns the active WWPNs of the FC ports across all VIOSes on system.

    :param adapter: pypowervm.adapter.Adapter for REST API communication.
    """
    vios_feed = vios.VIOS.get(adapter, xag=[c.XAG.VIO_STOR])
    wwpn_list = []
    for vwrap in vios_feed:
        wwpn_list.extend(vwrap.get_active_pfc_wwpns())
    return wwpn_list


def build_active_vio_feed_task(adapter, name='vio_feed_task', xag=(
        c.XAG.VIO_STOR, c.XAG.VIO_SMAP, c.XAG.VIO_FMAP)):
    """Builds a FeedTask for all active VIOSes.

    The transaction FeedTask enables users to collect a set of 'WrapperTasks'
    against a feed of entities (in this case a set of active VIOSes). The
    WrapperTask (within the FeedTask) handles lock and retry.

    This is useful to batch together a set of updates across a feed of elements
    (and multiple updates within a given wrapper).  This allows for significant
    performance improvements.

    :param adapter: The pypowervm adapter for the query.
    :param name: (Optional) The name of the feed manager.  Defaults to
                 vio_feed_task.
    :param xag: (Optional) Iterable of extended attributes to use.  If not
                specified, defaults to all mapping/storage options (as this is
                most common case for using a transaction manager).
    :raise NotEnoughActiveVioses: if there is not at least one active VIOS.
    """
    return tx.FeedTask(name, get_active_vioses(adapter, xag=xag, find_min=1))


def _rmc_down(vwrap):
    """Check if VIOS is in RMC Down state.

    :param vwrap: VIOS wrapper on which to check if RMC is down
    """
    if vwrap.is_mgmt_partition:
        return False
    if (vwrap.rmc_state not in _VALID_RMC_STATES and
            vwrap.state not in _DOWN_VM_STATES):
        return True
    return False


def _wait_for_vioses(adapter, max_wait_time):
    """Wait for VIOSes to stabilize, and report on their states.

    :param adapter: The pypowervm adapter for the query.
    :param max_wait_time: Maximum number of seconds to wait for running VIOSes
                          to get an active RMC connection.
    :return: List of all VIOSes returned by the REST API.
    :return: List of all VIOSes which are powered on, but with RMC inactive.
    """
    vios_wraps = []
    rmc_down_vioses = []
    sleep_step = 5
    while True:
        try:
            vios_wraps = vios.VIOS.get(adapter)
            rmc_down_vioses = [
                vwrap for vwrap in vios_wraps if _rmc_down(vwrap)]
            if not vios_wraps or (not rmc_down_vioses and get_active_vioses(
                    adapter, vios_wraps=vios_wraps)):
                # If there are truly no VIOSes (which should generally be
                # impossible if this code is running), we'll fail.
                # If at least one VIOS is up, and all active VIOSes have RMC,
                # we'll succeed.
                break
        except Exception as e:
            # Things like "Service Unavailable"
            LOG.warning(e)
        if max_wait_time <= 0:
            break
        time.sleep(sleep_step)
        max_wait_time -= sleep_step
    return vios_wraps, rmc_down_vioses


def validate_vios_ready(adapter, max_wait_time=None):
    """Check whether VIOS rmc is up and running on this host.

    Will query the VIOSes for a period of time attempting to ensure all
    running VIOSes get an active RMC.  If no VIOSes are ready by the timeout,
    ViosNotAvailable is raised.  If only some of the VIOSes had RMC go active
    by the end of the wait period, the method will complete.

    :param adapter: The pypowervm adapter for the query.
    :param max_wait_time: Integer, the maximum number of seconds to wait for
                          running VIOSes to get an active RMC connection.
                          Defaults to None in which case the wait time will
                          depend on the time since last system boot.
    :raises: A ViosNotAvailable exception if a VIOS is not available by a
             given timeout.
    """
    if max_wait_time is None:
        # Wait longer if we booted recently because VIOS RMC may take more time
        # to go active from boot.
        max_wait_time = (120 if (time.time() - psutil.BOOT_TIME) > 3600 else
                         600)

    # Used to keep track of VIOSes and reduce queries to API
    vios_wraps, rmc_down_vioses = _wait_for_vioses(adapter, max_wait_time)

    if rmc_down_vioses:
        LOG.warning(
            _('Timed out waiting for the RMC state of all the powered on '
              'Virtual I/O Servers to be active. Wait time was: %(time)d '
              'seconds. VIOSes that did not go active were: %(vioses)s.'),
            {'time': max_wait_time,
             'vioses': ', '.join([vio.name for vio in rmc_down_vioses])})

    # If we didn't get a single active VIOS then raise an exception
    if not get_active_vioses(adapter, vios_wraps=vios_wraps):
        raise ex.ViosNotAvailable(wait_time=max_wait_time)
