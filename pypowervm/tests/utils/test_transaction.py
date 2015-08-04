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

"""Tests for pypoowervm.utils.transaction."""

import fixtures
import mock
import six

import pypowervm.const as c
import pypowervm.exceptions as ex
import pypowervm.tests.wrappers.util.test_wrapper_abc as twrap
import pypowervm.utils.transaction as tx
import pypowervm.wrappers.entry_wrapper as ewrap
import pypowervm.wrappers.logical_partition as lpar

# Thread locking primitives are located slightly differently in py2 vs py3
SEM_ENTER = 'threading.%sSemaphore.__enter__' % ('_' if six.PY2 else '')
SEM_EXIT = 'threading.%sSemaphore.__exit__' % ('_' if six.PY2 else '')


class WrapperTaskFx(fixtures.Fixture):
    """Mocking and pseudo-logging for transaction primitives."""
    def __init__(self, wrapper):
        self._tx_log = []
        self._wrapper = wrapper
        self.get_p = mock.patch('pypowervm.wrappers.entry_wrapper.'
                                'EntryWrapperGetter.get')
        self.refresh_p = mock.patch('pypowervm.wrappers.entry_wrapper.'
                                    'EntryWrapper.refresh')
        self.enter_p = mock.patch(SEM_ENTER)
        self.exit_p = mock.patch(SEM_EXIT)

    def setUp(self):
        super(WrapperTaskFx, self).setUp()
        self.reset_log()

        # EntryWrapper.refresh()
        def _refresh():
            self.log('refresh')
            return self._wrapper
        mock_refresh = self.refresh_p.start()
        mock_refresh.side_effect = _refresh
        self.addCleanup(self.refresh_p.stop)

        # EntryWrapper.get()
        def _getter_get():
            self.log('get')
            return self._wrapper
        mock_get = self.get_p.start()
        mock_get.side_effect = _getter_get
        self.addCleanup(self.get_p.stop)

        # lockutils lock
        mock_lock = self.enter_p.start()
        mock_lock.side_effect = lambda *a, **k: self.log('lock')
        self.addCleanup(self.enter_p.stop)

        # lockutils unlock
        mock_unlock = self.exit_p.start()
        mock_unlock.side_effect = lambda *a, **k: self.log('unlock')
        self.addCleanup(self.exit_p.stop)

    def get_log(self):
        return self._tx_log

    def log(self, val):
        self._tx_log.append(val)

    def reset_log(self):
        self._tx_log = []


class TestWrapperTask(twrap.TestWrapper):
    file = 'lpar.txt'
    wrapper_class_to_test = lpar.LPAR

    def setUp(self):
        super(TestWrapperTask, self).setUp()
        self.getter = lpar.LPAR.getter(self.adpt, 'getter_uuid')
        # Set this up for getter.get()
        self.adpt.read.return_value = self.dwrap.entry
        self.tracker = mock.Mock(counter=0)

    class LparNameAndMem(tx.Subtask):
        """Subtask modifying an LPAR's name and desired memory."""
        def execute(self, lpar_wrapper, new_name, des_mem=None, logger=None):
            """Modify an LPAR's name and desired memory.

            :param lpar_wrapper: The LPAR EntryWrapper to update.
            :param new_name: The new name to give the LPAR.
            :param des_mem: (Optional) The new desired memory value, an int.
            :param logger: (Optional) If specified, "log" the class name for
                           test inspection purposes.
            :return: The (possibly modified) lpar_wrapper.
            """
            update_needed = False
            if logger:
                logger.log('LparNameAndMem_%s' % new_name)
            old_name = lpar_wrapper.name
            if old_name != new_name:
                lpar_wrapper.name = new_name
                update_needed = True
            if des_mem is not None:
                orig_mem = lpar_wrapper.mem_config.desired
                if des_mem != orig_mem:
                    lpar_wrapper.mem_config.desired = des_mem
                    update_needed = True
            return update_needed

    @staticmethod
    def retry_twice(wrapper, tracker, logger):
        # Force a couple of retries
        tracker.counter += 1
        logger.log('update %d' % tracker.counter)
        if tracker.counter < 3:
            raise ex.HttpError(
                "mismatch", mock.Mock(status=c.HTTPStatus.ETAG_MISMATCH))
        return wrapper

    @mock.patch('oslo_concurrency.lockutils.Semaphores.get')
    def test_synchronized_called_with_uuid(self, mock_semget):
        """Ensure the synchronizer is locking with the first arg's .uuid."""
        @tx.entry_transaction
        def foo(wrapper_or_getter):
            pass

        # At this point, the outer decorator has been invoked, but the
        # synchronizing decorator has not.
        self.assertEqual(0, mock_semget.call_count)

        # If we call the decorated method with an EntryWrapper, synchronize
        # should be invoked with the EntryWrapper's UUID
        foo(self.dwrap)
        self.assertEqual(1, mock_semget.call_count)
        mock_semget.assert_called_with('089FFB20-5D19-4A8C-BB80-13650627D985')

        # Calling with an EntryWrapperGetter should synchronize on the getter's
        # registered UUID.  (IRL, this will match the wrapper's UUID.  Here we
        # are making sure the right code path is being taken.)
        mock_semget.reset_mock()
        foo(self.getter)
        self.assertEqual(1, mock_semget.call_count)
        mock_semget.assert_called_with('getter_uuid')

    def test_sequence(self):
        """Prove the sequence of events on a transaction-decorated method.

        We expect it to look like:
        lock
        get the wrapper if necessary
        invoke the method
        while the method raises etag error, refresh the wrapper and re-invoke
        unlock
        """
        txfx = self.useFixture(WrapperTaskFx(self.dwrap))

        @tx.entry_transaction
        def foo(wrapper_or_getter):
            # Always converted by now
            self.assertIsInstance(wrapper_or_getter, ewrap.EntryWrapper)
            return self.retry_twice(wrapper_or_getter, self.tracker, txfx)

        # With an EntryWrapperGetter, get() is invoked
        self.assertEqual(self.dwrap, foo(self.getter))
        self.assertEqual(['lock', 'get', 'update 1', 'refresh', 'update 2',
                          'refresh', 'update 3', 'unlock'], txfx.get_log())

        # With an EntryWrapper, get() is not invoked
        self.tracker.counter = 0
        txfx.reset_log()
        self.assertEqual(self.dwrap, foo(self.dwrap))
        self.assertEqual(['lock', 'update 1', 'refresh', 'update 2', 'refresh',
                          'update 3', 'unlock'], txfx.get_log())

    @staticmethod
    def tx_subtask_invoke(tst, wrapper):
        """Simulates how Subtasks are invoked by WrapperTask.

        :param tst: A Subtask
        :param wrapper: The wrapper with which to invoke execute()
        :return: The value returned by execute()
        """
        return tst.execute(wrapper, *tst.save_args, **tst.save_kwargs)

    def test_transaction_subtask(self):
        """Tests around Subtask."""
        # Same name, should result in no changes and no update_needed
        txst1 = self.LparNameAndMem('z3-9-5-126-127-00000001')
        self.assertFalse(self.tx_subtask_invoke(txst1, self.dwrap))
        self.assertEqual('z3-9-5-126-127-00000001', self.dwrap.name)
        self.assertEqual(512, self.dwrap.mem_config.desired)
        # New name should prompt update_needed.  Specified-but-same des_mem.
        txst2 = self.LparNameAndMem('new-name', des_mem=512)
        self.assertTrue(self.tx_subtask_invoke(txst2, self.dwrap))
        self.assertEqual('new-name', self.dwrap.name)
        self.assertEqual(512, self.dwrap.mem_config.desired)
        # New name and mem should prompt update_needed
        txst3 = self.LparNameAndMem('newer-name', des_mem=1024)
        self.assertTrue(self.tx_subtask_invoke(txst3, self.dwrap))
        self.assertEqual('newer-name', self.dwrap.name)
        self.assertEqual(1024, self.dwrap.mem_config.desired)
        # Same name and explicit same mem - no update_needed
        txst4 = self.LparNameAndMem('newer-name', des_mem=1024)
        self.assertFalse(self.tx_subtask_invoke(txst4, self.dwrap))
        self.assertEqual('newer-name', self.dwrap.name)
        self.assertEqual(1024, self.dwrap.mem_config.desired)

    def test_transaction_subtask_returns(self):
        """Test that execute methods' return values are processed properly."""
        # Use internal _FunctorSubtask to make this easier.  Bonus: testing
        # _FunctorSubtask at the same time.

        def returns_second_arg(wrapper, boolable):
            """Used to test various boolable single returns."""
            return boolable

        # Various valid 'False' boolables - update not needed
        falseables = (0, '', [], {}, False)
        for falseable in falseables:
            txst = tx._FunctorSubtask(returns_second_arg, falseable)
            self.assertFalse(self.tx_subtask_invoke(txst, self.dwrap))

        # Various valid 'True' boolables - update needed
        trueables = (1, 'string', [0], {'k': 'v'}, True)
        for trueable in trueables:
            txst = tx._FunctorSubtask(returns_second_arg, trueable)
            self.assertTrue(self.tx_subtask_invoke(txst, self.dwrap))

    @mock.patch('pypowervm.wrappers.entry_wrapper.EntryWrapper.update')
    def test_transaction1(self, mock_update):
        txfx = self.useFixture(WrapperTaskFx(self.dwrap))

        def _update():
            txfx.log('update')
            # Since we're passing around self.dwrap and modifying it in-place,
            # this return should have the changes in it.
            return self.dwrap
        mock_update.side_effect = _update

        # Must supply a wrapper or getter to instantiate
        self.assertRaises(ValueError, tx.WrapperTask, 'foo', 'bar')

        # Create a valid WrapperTask
        tx1 = tx.WrapperTask('tx1', self.getter)
        self.assertEqual('tx1', tx1.name)
        self.assertEqual('wrapper_getter_uuid', tx1.provides)
        # Nothing has been run yet
        self.assertEqual([], txfx.get_log())
        # Try running with no subtasks
        self.assertRaises(ex.WrapperTaskNoSubtasks, tx1.execute)
        # Try adding something that isn't a Subtask
        self.assertRaises(ValueError, tx1.add_subtask, 'Not a Subtask')
        # Error paths don't run anything.
        self.assertEqual([], txfx.get_log())

        # Add a subtask that doesn't change anything
        tx1.add_subtask(self.LparNameAndMem('z3-9-5-126-127-00000001',
                                            logger=txfx))
        # Adding a subtask does not run anything
        self.assertEqual([], txfx.get_log())

        # Get the wrapper - this should invoke GET, but *not* under lock
        self.assertEqual(self.dwrap, tx1.wrapper)
        self.assertEqual(['get'], txfx.get_log())

        # Run the transaction
        lwrap = tx1.execute()
        # The name should be unchanged
        self.assertEqual('z3-9-5-126-127-00000001', lwrap.name)
        # And update should not have been called
        self.assertEqual(0, mock_update.call_count)
        # ...which should also be reflected in the log.  Note that 'get' is NOT
        # called a second time.
        self.assertEqual([
            'get', 'lock', 'LparNameAndMem_z3-9-5-126-127-00000001', 'unlock'],
            txfx.get_log())

        txfx.reset_log()
        # These subtasks do change the name.
        tx1.add_subtask(self.LparNameAndMem('new_name', logger=txfx))
        tx1.add_subtask(self.LparNameAndMem('newer_name', logger=txfx))
        # But this one doesn't.  We're making sure the last 'no update needed'
        # doesn't make the overall update_needed status False.
        tx1.add_subtask(self.LparNameAndMem('newer_name', logger=txfx))
        # Get the wrapper - this should *not* reinvoke GET
        self.assertEqual(self.dwrap, tx1.wrapper)
        self.assertEqual([], txfx.get_log())
        # Now execute the transaction
        lwrap = tx1.execute()
        # Update should have been called.
        self.assertTrue(1, mock_update.call_count)
        # The last change should be the one that stuck
        self.assertEqual('newer_name', lwrap.name)
        # Check the overall order
        self.assertEqual([
            'lock', 'LparNameAndMem_z3-9-5-126-127-00000001',
            'LparNameAndMem_new_name', 'LparNameAndMem_newer_name',
            'LparNameAndMem_newer_name', 'update', 'unlock'], txfx.get_log())

        # Test 'cloning' the subtask list
        txfx.reset_log()
        tx2 = tx.WrapperTask('tx2', self.getter, subtasks=tx1.subtasks)
        # Add another one to make sure it goes at the end
        tx2.add_subtask(self.LparNameAndMem('newest_name', logger=txfx))
        # Add one to the original transaction to make sure it doesn't affect
        # this one.
        tx1.add_subtask(self.LparNameAndMem('bogus_name', logger=txfx))
        lwrap = tx2.execute()
        # Update should have been called.
        self.assertTrue(1, mock_update.call_count)
        # The last change should be the one that stuck
        self.assertEqual('newest_name', lwrap.name)
        # Check the overall order.  This one GETs under lock.
        self.assertEqual([
            'lock', 'get', 'LparNameAndMem_z3-9-5-126-127-00000001',
            'LparNameAndMem_new_name', 'LparNameAndMem_newer_name',
            'LparNameAndMem_newer_name', 'LparNameAndMem_newest_name',
            'update', 'unlock'], txfx.get_log())

    @mock.patch('pypowervm.wrappers.entry_wrapper.EntryWrapper.update')
    def test_transaction2(self, mock_update):
        # Now:
        # o Fake like update forces retry
        # o Test add_functor_subtask, including chaining
        # o Ensure GET is deferred when .wrapper() is not called ahead of time.
        # o Make sure subtask args are getting to the subtask.
        txfx = self.useFixture(WrapperTaskFx(self.dwrap))

        def _update_retries_twice():
            return self.retry_twice(self.dwrap, self.tracker, txfx)
        mock_update.side_effect = _update_retries_twice

        def functor(wrapper, arg1, arg2, kwarg3=None, kwarg4=None):
            txfx.log('functor')
            # Make sure args are getting here
            self.assertEqual(['arg', 1], arg1)
            self.assertEqual('arg2', arg2)
            self.assertIsNone(kwarg3)
            self.assertEqual('kwarg4', kwarg4)
            return wrapper, True
        # Instantiate-add-execute chain
        tx.WrapperTask('tx2', self.getter).add_functor_subtask(
            functor, ['arg', 1], 'arg2', kwarg4='kwarg4').execute()
        # Update should have been called thrice (two retries)
        self.assertTrue(3, mock_update.call_count)
        # Check the overall order
        self.assertEqual([
            'lock', 'get', 'functor', 'update 1', 'refresh', 'functor',
            'update 2', 'refresh', 'functor', 'update 3', 'unlock'],
            txfx.get_log())


class TestFeedTask(twrap.TestWrapper):
    file = 'lpar.txt'
    wrapper_class_to_test = lpar.LPAR

    @mock.patch('pypowervm.wrappers.entry_wrapper.FeedGetter.get')
    def test_empty_feed(self, mock_get):
        mock_get.return_value = []
        # We're allowed to initialize it with a FeedGetter
        fm = tx.FeedTask('name', ewrap.FeedGetter('mock', 'mock'))
        # But as soon as we call a 'greedy' method, which does a .get, we raise
        self.assertRaises(ex.FeedTaskEmptyFeed, fm.get_wrapper_task, 'uuid')

        # Init with an explicit empty feed (list) raises right away
        self.assertRaises(ex.FeedTaskEmptyFeed, tx.FeedTask, 'name', [])
