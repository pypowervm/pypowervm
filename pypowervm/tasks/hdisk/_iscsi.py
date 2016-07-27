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

from oslo_log import log as logging

import pypowervm.const as c
from pypowervm.i18n import _
from pypowervm.tasks import partition
from pypowervm.wrappers import job
from pypowervm.wrappers.virtual_io_server import VIOS

LOG = logging.getLogger(__name__)
_JOB_NAME = "ISCSIDiscovery"


def discover_iscsi(adapter, host_ip, user, password, iqn, vios_uuid=None):
    """Runs iscsi discovery and login commands

    :param adapter: pypowervm adapter
    :param host_ip: The ip address of the iscsi target.
    :param user: The username needed for authentication.
    :param password: The password needed for authentication.
    :param IQN: The IQN (iSCSI Qualified Name) of the created volume on the
                target. (e.g. iqn.2016-06.world.srv:target00)
    :return: The device name of the created volume.
    """
    if vios_uuid is None:
        mgmt_part = partition.get_mgmt_partition(adapter)
        vios_uuid = mgmt_part.uuid

    resp = adapter.read(VIOS.schema_type, vios_uuid,
                        suffix_type=c.SUFFIX_TYPE_DO, suffix_parm=(_JOB_NAME))
    job_wrapper = job.Job.wrap(resp)

    # Create job parameters
    job_parms = [job_wrapper.create_job_parameter('hostIp', host_ip)]
    job_parms.append(job_wrapper.create_job_parameter('password', password))
    job_parms.append(job_wrapper.create_job_parameter('user', user))

    try:
        job_wrapper.run_job(vios_uuid, job_parms=job_parms, timeout=120)
        results = job_wrapper.get_job_results_as_dict()
    except Exception:
        raise

    # DEV_OUTPUT: [IQN1 dev1, IQN2 dev2]
    output = results.get('DEV_OUTPUT')
    # Find dev corresponding to given IQN
    for dev in output:
        outiqn, outname = dev.split()
        if outiqn == iqn:
            return outname
    LOG.error(_("Expected IQN: %(IQN) not found on iscsi target %(host_ip"),
              {'IQN': iqn, 'host_ip': host_ip})
    return None
