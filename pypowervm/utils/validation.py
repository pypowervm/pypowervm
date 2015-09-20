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

"""Extended validation utilities."""

import abc
import logging
import six

from pypowervm.i18n import _
from pypowervm.wrappers import base_partition as bp

LOG = logging.getLogger(__name__)


class ValidatorException(Exception):
    """Exceptions thrown from the validators."""
    pass


class LPARWrapperValidator(object):
    """LPAR Validator.

    This class implements additional validation for LPARs for use
    during resize or deployment.

    It is meant to catch any violations that would cause errors at
    the PowerVM management interface.
    """
    def __init__(self, lpar_w, host_w, cur_lpar_w=None):
        """Initialize the validator

        :param lpar_w: LPAR wrapper intended to be validated
        :param host_w: managed_system wrapper intended to be validated
            against such as making sure the host has the desired resources
            of the LPAR available.
        :param cur_lpar_w: (Optional) current LPAR wrapper used to validate
            deltas during a resize operation. If this is passed in then it
            assumes resize validation.
        """
        self.lpar_w = lpar_w
        self.host_w = host_w
        self.cur_lpar_w = cur_lpar_w

    def validate_all(self):
        """Invoke attribute validation classes to perform validation"""
        ProcValidator(self.lpar_w, self.host_w,
                      cur_lpar_w=self.cur_lpar_w).validate()
        MemValidator(self.lpar_w, self.host_w,
                     cur_lpar_w=self.cur_lpar_w).validate()
        CapabilitiesValidator(self.lpar_w, self.host_w,
                              cur_lpar_w=self.cur_lpar_w).validate()


@six.add_metaclass(abc.ABCMeta)
class BaseValidator(object):
    """Base Validator.

    This class is responsible for delegating validation depending on
    if it's a deploy, active resize, or inactive resize.

    If the caller intends to perform resize validation then they must pass
    the cur_lpar_w argument. The cur_lpar_w is the current LPAR wrapper
    describing the LPAR before any resizing has taken place, while lpar_w
    represents the LPAR with new (resized) values. If cur_lpar_w is None
    then deploy validation logic will ensue.
    """
    def __init__(self, lpar_w, host_w, cur_lpar_w=None):
        """Initialize LPAR and System Wrappers."""
        self.lpar_w = lpar_w
        self.host_w = host_w
        self.cur_lpar_w = cur_lpar_w

    def validate(self):
        """Determines what validation is requested and invokes it."""
        # Deploy
        self._populate_new_values()
        if self.cur_lpar_w is None:
            self._validate_deploy()
        # Resize
        else:
            self._can_modify()
            self._populate_resize_diffs()
            # Active Resize
            if self.cur_lpar_w.state == bp.LPARState.RUNNING:
                self._validate_active_resize()
            # Inactive Resize
            else:
                self._validate_inactive_resize()
        self._validate_common()

    @abc.abstractmethod
    def _populate_new_values(self):
        """Abstract method for populating deploy values

        This method will always be called in validate() and should
        populate instance attributes with the new LPARWrapper
        values.
        """

    @abc.abstractmethod
    def _populate_resize_diffs(self):
        """Abstract method for populating resize values

        This method will only be called in validate() for resize
        operations and should populate instance attributes with
        the differences between the old and new LPARWrapper values.
        """

    @abc.abstractmethod
    def _validate_deploy(self):
        """Abstract method for deploy validation only."""

    @abc.abstractmethod
    def _validate_active_resize(self):
        """Abstract method for active resize validation only."""

    @abc.abstractmethod
    def _validate_inactive_resize(self):
        """Abstract method for inactive resize validation only."""

    @abc.abstractmethod
    def _validate_common(self):
        """Abstract method for common validation

        This method should be agnostic to the operation being validated
        (deploy or resize) because the instance attributes will
        be populated accordingly in validate().
        """

    @abc.abstractmethod
    def _can_modify(self):
        """Abstract method to check if resource may be modified

        This method should invoke the corresponding can_modify
        method in the LPAR class for the resource and raise an
        exception if it returns False. Should only be called for
        resize validation when cur_lpar_w is passed in.
        """

    def _validate_host_has_available_res(self, des, avail, res_name):
        if round(des, 2) > round(avail, 2):
            ex_args = {'requested': '%.2f' % des,
                       'avail': '%.2f' % avail,
                       'instance_name': self.lpar_w.name,
                       'res_name': res_name}
            msg = _("Insufficient available %(res_name)s on host for virtual "
                    "machine '%(instance_name)s' (%(requested)s "
                    "requested, %(avail)s available)") % ex_args
            LOG.error(msg)
            raise ValidatorException(msg)


class MemValidator(BaseValidator):
    """Memory Validator.

    This class implements memory validation for lpars in the case of
    deploy, inactive resize, and active resize.

    Instance attributes populated by _populate_new_values
    :attr des_mem: desired memory of the new lpar
    :attr max_mem: maximum memory of the new lpar
    :attr min_mem: minimum memory of the new lpar
    :attr avail_mem: available memory on the host
    :attr res_name: name of the resource
    """
    def _populate_new_values(self):
        """Set newly desired LPAR attributes as instance attributes."""
        mem_cfg = self.lpar_w.mem_config
        self.des_mem = mem_cfg.desired
        self.max_mem = mem_cfg.max
        self.min_mem = mem_cfg.min
        self.avail_mem = self.host_w.memory_free
        self.res_name = _('memory')

    def _populate_resize_diffs(self):
        """Calculate lpar_w vs cur_lpar_w diffs and set as attributes."""
        deltas = self._calculate_resize_deltas()
        self.delta_des_mem = deltas['delta_mem']
        self.delta_max_mem = deltas['delta_max_mem']

    def _validate_deploy(self):
        """Enforce validation rules specific to LPAR deployment."""
        self._validate_host_has_available_res(
            self.des_mem, self.avail_mem, self.res_name)

    def _validate_active_resize(self):
        """Enforce validation rules specific to active resize."""
        curr_mem_cfg = self.cur_lpar_w.mem_config
        curr_min_mem = curr_mem_cfg.min
        curr_max_mem = curr_mem_cfg.max
        # min/max values cannot be changed while lpar is running.
        if self.max_mem != curr_max_mem or self.min_mem != curr_min_mem:
            msg = (_("Changing minimum or maximum memory is not supported "
                     "while virtual machine %s is running. "
                     "It must be powered off first.") % self.cur_lpar_w.name)
            raise ValidatorException(msg)
        # Common validations for both active & inactive resizes.
        self._validate_resize_common()

    def _validate_inactive_resize(self):
        """Enforce validation rules specific to inactive resize."""
        self._validate_resize_common()

    def _validate_common(self):
        """Enforce operation agnostic validation rules."""
        # TODO(IBM):
        pass

    def _can_modify(self):
        """Checks mem dlpar and rmc state if LPAR not activated."""
        modifiable, reason = self.cur_lpar_w.can_modify_mem()
        if not modifiable:
            LOG.error(reason)
            raise ValidatorException(reason)

    def _validate_resize_common(self):
        """Validation rules common for both active and inactive resizes.

        Helper method to enforce validation rules that are common for
        both active and inactive resizes.
        """
        self._validate_host_has_available_res(self.delta_des_mem,
                                              self.avail_mem,
                                              self.res_name)

    def _calculate_resize_deltas(self):
        """Helper method to calculate the memory deltas for resize operation.

        :return dict of memory deltas.
        """
        deltas = {}
        # Current LPAR values
        curr_mem_cfg = self.cur_lpar_w.mem_config
        curr_des_mem = curr_mem_cfg.desired
        curr_max_mem = curr_mem_cfg.max

        # Calculate memory deltas
        deltas['delta_mem'] = self.des_mem - curr_des_mem
        deltas['delta_max_mem'] = self.max_mem - curr_max_mem
        return deltas


class ProcValidator(BaseValidator):
    """Processor Validator.

    This class implements processor validation for LPARs in the case of
    deploy, inactive resize, and active resize.

    Instance attributes populated by _populate_new_values
    :attr has_dedicated: LPAR has dedicated processors boolean
    :attr procs_avail: available procs on host
    :attr des_procs: desired processors from new LPAR
    :attr res_name: name of the resource
    :attr max_procs_per_aix_linux_lpar: max procs per LPAR on host
    :attr max_sys_procs_limit: LPAR max procs limit on host
    :attr des_vcpus: LPAR desired vcpus
    :attr max_vcpus: LPAR max vcpus
    :attr min_vcpus: LPAR min vcpus
    :attr proc_compat_mode: Processor compatibility mode
    :attr pool_id: LPAR shared processor pool ID (only for shared proc mode)
    :attr max_proc_units: LPAR max proc units (only for shared processor mode)
    :attr min_proc_units: LPAR min proc units (only for shared processor mode)
    """
    def _populate_new_values(self):
        """Set newly desired LPAR values as instance attributes."""
        self.has_dedicated = self.lpar_w.proc_config.has_dedicated
        self.procs_avail = self.host_w.proc_units_avail
        self.proc_compat_mode = self.lpar_w.proc_compat_mode
        if self.has_dedicated:
            self._populate_dedicated_proc_values()
        else:
            self._populate_shared_proc_values()

    def _populate_dedicated_proc_values(self):
        """Set dedicated proc values as instance attributes."""
        ded_proc_cfg = self.lpar_w.proc_config.dedicated_proc_cfg
        self.des_procs = ded_proc_cfg.desired
        self.res_name = _('CPUs')
        # Proc host limits for dedicated proc
        self.max_procs_per_aix_linux_lpar = (
            self.host_w.max_procs_per_aix_linux_lpar)
        self.max_sys_procs_limit = self.host_w.max_sys_procs_limit

        # VCPUs doesn't mean anything in dedicated proc cfg
        # FAIP in dedicated proc cfg vcpus == procs for naming convention
        self.des_vcpus = self.des_procs
        self.max_vcpus = ded_proc_cfg.max
        self.min_vcpus = ded_proc_cfg.min

    def _populate_shared_proc_values(self):
        """Set shared proc values as instance attributes."""
        shr_proc_cfg = self.lpar_w.proc_config.shared_proc_cfg
        self.des_procs = shr_proc_cfg.desired_units
        self.res_name = _('processing units')
        # VCPU host limits for shared proc
        self.max_procs_per_aix_linux_lpar = (
            self.host_w.max_vcpus_per_aix_linux_lpar)
        self.max_sys_procs_limit = self.host_w.max_sys_vcpus_limit

        self.des_vcpus = shr_proc_cfg.desired_virtual
        self.max_vcpus = shr_proc_cfg.max_virtual
        self.min_vcpus = shr_proc_cfg.min_virtual
        self.max_proc_units = shr_proc_cfg.max_units
        self.min_proc_units = shr_proc_cfg.min_units
        self.pool_id = shr_proc_cfg.pool_id

    def _populate_resize_diffs(self):
        """Calculate lpar_w vs cur_lpar_w diffs and set as attributes."""
        deltas = self._calculate_resize_deltas()
        self.delta_des_vcpus = deltas['delta_vcpu']

    def _validate_deploy(self):
        """Enforce validation rules specific to LPAR deployment."""
        self._validate_host_has_available_res(
            self.des_procs, self.procs_avail, self.res_name)

    def _validate_active_resize(self):
        """Enforce validation rules specific to active resize."""
        # Extract current values from existing LPAR.
        curr_has_dedicated = self.cur_lpar_w.proc_config.has_dedicated
        if curr_has_dedicated:
            lpar_proc_config = self.cur_lpar_w.proc_config.dedicated_proc_cfg
            curr_max_vcpus = lpar_proc_config.max
            curr_min_vcpus = lpar_proc_config.min
        else:
            lpar_proc_config = self.cur_lpar_w.proc_config.shared_proc_cfg
            curr_max_vcpus = lpar_proc_config.max_virtual
            curr_min_vcpus = lpar_proc_config.min_virtual
            curr_max_proc_units = lpar_proc_config.max_units
            curr_min_proc_units = lpar_proc_config.min_units

        # min/max cannot be changed while LPAR is running.
        if (self.max_vcpus != curr_max_vcpus or
                self.min_vcpus != curr_min_vcpus):
            msg = (_("Changing minimum or maximum processors is not supported "
                     "while virtual machine %s is running. "
                     "It must be powered off first.") % self.cur_lpar_w.name)
            raise ValidatorException(msg)

        if not self.has_dedicated and not curr_has_dedicated:
            curr_min_proc_units = round(float(curr_min_proc_units), 2)
            curr_max_proc_units = round(float(curr_max_proc_units), 2)
            if (round(self.max_proc_units, 2) != curr_max_proc_units or
                    round(self.min_proc_units, 2) != curr_min_proc_units):
                msg = (_("Changing minimum or maximum processor units is not "
                         "supported while virtual machine %s is running. "
                         "It must be powered off first.") %
                       self.cur_lpar_w.name)
                raise ValidatorException(msg)

        # Processor Compatibility mode cannot be changed while LPAR is running.
        curr_proc_compat = self.cur_lpar_w.proc_compat_mode
        curr_pend_proc_compat = self.cur_lpar_w.pending_proc_compat_mode
        if self.proc_compat_mode is not None:
            proc_compat = self.proc_compat_mode.lower()
            if (proc_compat != curr_proc_compat.lower() and
                    (proc_compat != curr_pend_proc_compat.lower())):
                # If requested was not the same as current, this is
                # not supported while instance is running exception
                msg = (_("Changing processor compatibility mode is not "
                         "supported while virtual machine %s is "
                         "running. It must be powered off first.") %
                       self.cur_lpar_w.name)
                raise ValidatorException(msg)

        # Changing processing mode is not supported while LPAR is running.
        if self.has_dedicated != curr_has_dedicated:
            msg = (_("Changing Processing mode is not supported while "
                     "virtual machine %s is running. "
                     "It must be powered off first.") % self.cur_lpar_w.name)
            raise ValidatorException(msg)

        # Validations common for both active & inactive resizes.
        self._validate_resize_common()

    def _validate_inactive_resize(self):
        """Enforce validation rules specific to inactive resize."""
        self._validate_resize_common()

    def _validate_common(self):
        """Enforce operation agnostic validation rules."""
        self._validate_host_max_allowed_procs_per_lpar()
        self._validate_host_max_sys_procs_limit()

    def _can_modify(self):
        """Checks proc dlpar and rmc state if LPAR not activated."""
        modifiable, reason = self.cur_lpar_w.can_modify_proc()
        if not modifiable:
            LOG.error(reason)
            raise ValidatorException(reason)

    def _validate_host_max_allowed_procs_per_lpar(self):
        if self.des_vcpus > self.max_procs_per_aix_linux_lpar:
            ex_args = {'vcpus': self.des_vcpus,
                       'max_allowed': self.max_procs_per_aix_linux_lpar,
                       'instance_name': self.lpar_w.name}
            msg = _("The desired processors (%(vcpus)d) cannot be above "
                    "the maximum allowed processors per partition "
                    "(%(max_allowed)d) for virtual machine "
                    "'%(instance_name)s'.") % ex_args
            LOG.error(msg)
            raise ValidatorException(msg)

    def _validate_host_max_sys_procs_limit(self):
        if self.max_vcpus > self.max_sys_procs_limit:
            ex_args = {'vcpus': self.max_vcpus,
                       'max_allowed': self.max_sys_procs_limit,
                       'instance_name': self.lpar_w.name}
            msg = _("The maximum processors (%(vcpus)d) cannot be above "
                    "the maximum system capacity processor limit "
                    "(%(max_allowed)d) for virtual machine "
                    "'%(instance_name)s'.") % ex_args
            LOG.error(msg)
            raise ValidatorException(msg)

    def _validate_resize_common(self):
        """Validation rules common for both active and inactive resizes.

        Helper method to enforce validation rules that are common for
        both active and inactive resizes.
        """
        curr_has_dedicated = self.cur_lpar_w.proc_config.has_dedicated
        curr_proc_pool_id = self.cur_lpar_w.proc_config.shared_proc_cfg.pool_id
        if curr_has_dedicated and not self.has_dedicated:
            # Resize from Dedicated Mode to Shared Mode
            if self.pool_id != 0:
                msg = (_("Changing shared processor pool name to a pool other "
                         "than DefaultPool is not "
                         "supported for virtual machine %s.")
                       % self.cur_lpar_w.name)
                raise ValidatorException(msg)

        if not self.has_dedicated and not curr_has_dedicated:
            curr_proc_pool_id = self.cur_lpar_w.proc_config.\
                shared_proc_cfg.pool_id
            if curr_proc_pool_id != self.pool_id:
                msg = (_("Changing shared processor pool name is not "
                         "supported for virtual machine %s.")
                       % self.cur_lpar_w.name)
                raise ValidatorException(msg)

        self._validate_host_has_available_res(self.delta_des_vcpus,
                                              self.procs_avail,
                                              self.res_name)

    def _calculate_resize_deltas(self):
        """Helper method to calculate the procs deltas for resize operation.

        :return dict of processor deltas.
        """
        deltas = {}
        # Extract current values from existing LPAR.
        curr_has_dedicated = self.cur_lpar_w.proc_config.has_dedicated
        if curr_has_dedicated:
            lpar_proc_config = self.cur_lpar_w.proc_config.dedicated_proc_cfg
            curr_des_vcpus = lpar_proc_config.desired
        else:
            lpar_proc_config = self.cur_lpar_w.proc_config.shared_proc_cfg
            curr_des_vcpus = lpar_proc_config.desired_virtual
            curr_proc_units = lpar_proc_config.desired_units

        # Calculate VCPU deltas
        deltas['delta_vcpu'] = self.des_vcpus - curr_des_vcpus

        # If this is dedicated processor mode, there are no proc_units.
        if self.has_dedicated:
            if not curr_has_dedicated and curr_proc_units is not None:
                # Resize from Shared to Dedicated mode
                deltas['delta_vcpu'] = (
                    round(self.des_vcpus - curr_proc_units, 2))
        else:
            if curr_has_dedicated:
                # Resize from Dedicated to Shared mode
                deltas['delta_vcpu'] = (
                    round(self.des_procs - curr_des_vcpus, 2))
            else:
                deltas['delta_vcpu'] = (
                    round(self.des_procs - curr_proc_units, 2))
        return deltas


class CapabilitiesValidator(BaseValidator):
    """Capabilities Validator.

    This class implements capabilities validation for lpars in the case of
    deploy, inactive resize, and active resize.

    Instance attributes populated by _populate_new_values
    :attr srr_enabled: srr capability of the lpar
    """
    def _populate_new_values(self):
        """Set newly desired resize attributes as instance attributes."""
        self.srr_enabled = self.lpar_w.srr_enabled

    def _validate_active_resize(self):
        """Enforce validation rules specific to active resize."""
        # Simplified Remote Restart capability cannot be changed while LPAR is
        # running.
        curr_srr_enabled = self.cur_lpar_w.srr_enabled
        if curr_srr_enabled != self.srr_enabled:
            msg = (_("Changing simplified remote restart capability is not "
                     "supported while virtual machine %s is running. "
                     "It must be powered off first.") % self.cur_lpar_w.name)
            raise ValidatorException(msg)

    def _populate_resize_diffs(self):
        """Calculate lpar_w vs cur_lpar_w diffs and set as attributes."""
        pass

    def _validate_deploy(self):
        """Enforce validation rules specific to LPAR deployment."""
        pass

    def _validate_inactive_resize(self):
        """Enforce validation rules specific to inactive resize."""
        pass

    def _validate_common(self):
        """Enforce operation agnostic validation rules."""
        pass

    def _can_modify(self):
        """Check if capabilities may be modified."""
        pass
