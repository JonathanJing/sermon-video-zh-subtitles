"""Precise pre-provider classification and collector failure halt; zero models."""
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
from scripts import sermon_diagnostic_prefect_flow as flow,sermon_historical_identity as identity
from scripts import sermon_accounting as accounting,sermon_review_contracts as c,sermon_log_profile as profile
from tests.test_sermon_diagnostic_prefect_flow import SessionFixture,config_fixture


class PreciseFlowFailureTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.session=SessionFixture(self.root);self.config=config_fixture(self.root)
        self.enterContext(patch.object(flow,'_session_class',return_value=SessionFixture))
        self.dag=flow.DiagnosticDAG(self.session,self.config)

    def run_failure(self,error):
        def fail_locale(*args,**kwargs):raise error
        self.session.run_locale=fail_locale
        self.dag.freeze();self.dag.execute('source.existing')
        return self.dag.execute('text.ko')

    def test_typed_trusted_pre_provider_rejection_is_blocked_not_transport_unknown(self):
        error=identity.HistoricalIdentityPreDispatchRejected('historical_current_code_changed')
        with profile.session(self.root/'logs','precise-local-rejection',work_kind='engineering',evidence_mode='synthetic'):
            observed=self.run_failure(error)
        self.assertEqual(observed['executionStatus'],'blocked');self.assertIs(observed['processed'],False)
        self.assertEqual(observed['failurePhase'],'before_locale_provider_dispatch')
        self.assertIs(observed['providerDispatchOccurred'],False)
        self.assertEqual(observed['reason'],'historical_current_code_changed')
        self.assertFalse(observed['readyForDownstream'])
        self.assertEqual(self.session.calls,[('source',None)])

    def test_typed_failure_reason_is_finite_and_tamper_never_leaks_message(self):
        error=identity.HistoricalIdentityPreDispatchRejected('historical_current_code_changed')
        for field,value in (('reason_code','private_body'),('phase','after_dispatch'),('provider_dispatch_occurred',True)):
            with self.assertRaises(AttributeError):setattr(error,field,value)
        error._reason_code='private_body'
        error.args=('private_body',)
        with profile.session(self.root/'logs','tampered-local-code',work_kind='engineering',evidence_mode='synthetic'):
            observed=self.run_failure(error)
        self.assertEqual(observed['executionStatus'],'outcome_unknown')
        self.assertEqual(observed['reason'],'callback_or_evidence_not_confirmed')
        self.assertNotIn('providerDispatchOccurred',observed)

    def test_same_plain_contract_code_stays_conservative_unknown_and_no_provider_zero_guess(self):
        # No cumulative provider count is read to infer a per-locale dispatch.
        error=c.ContractError('historical_current_code_changed')
        self.session.subject.snapshot=lambda:(_ for _ in ()).throw(AssertionError('must not infer from global provider count'))
        with profile.session(self.root/'logs','plain-local-code',work_kind='engineering',evidence_mode='synthetic'):
            observed=self.run_failure(error)
        self.assertEqual(observed['executionStatus'],'outcome_unknown');self.assertIsNone(observed['processed'])
        self.assertNotIn('providerDispatchOccurred',observed)

    def test_accounting_failure_reraises_original_and_stops_all_later_locale_callbacks(self):
        error=accounting.AccountingWriteError('structured_logging_write_failed')
        with profile.session(self.root/'logs','accounting-failure',work_kind='engineering',evidence_mode='synthetic'):
            with self.assertRaises(accounting.AccountingWriteError) as caught:self.run_failure(error)
            self.assertIs(caught.exception,error)
            with self.assertRaises(accounting.AccountingWriteError) as again:self.dag.execute('text.zh-Hans')
            self.assertIs(again.exception,error)
        self.assertNotIn('text.ko',self.dag.observations)
        self.assertFalse((self.dag.root/'observations/text.ko').exists())
        self.assertEqual(self.session.calls,[('source',None)])

    def test_real_collector_terminal_failure_preserves_business_exception_and_halts(self):
        error=c.ContractError('synthetic_business_failure');emit=accounting._emit
        def failing_collector(event):
            if event.get('event')=='stage_finished' and event.get('stage')=='diagnostic.dag.locale':
                raise accounting.AccountingWriteError('structured_logging_write_failed')
            return emit(event)
        with profile.session(self.root/'logs','collector-terminal-failure',work_kind='engineering',evidence_mode='synthetic'):
            with patch.object(accounting,'_emit',side_effect=failing_collector):
                with self.assertRaises(c.ContractError) as caught:self.run_failure(error)
            self.assertIs(caught.exception,error);self.assertTrue(error.sermon_logging_failed)
            with self.assertRaises(c.ContractError) as again:self.dag.execute('text.zh-Hans')
            self.assertIs(again.exception,error)
        self.assertNotIn('text.ko',self.dag.observations)
        self.assertEqual(self.session.calls,[('source',None)])


if __name__=='__main__':unittest.main()
