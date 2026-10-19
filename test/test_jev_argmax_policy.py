"""Jev action policy: use the distribution winner, not confidence thresholds."""
import pytest
from pydantic import ValidationError

from tools.jev_browser import JevRunInput, make_jev_browser_tools
from test.test_jev_browser import FakeBackend, answer, enabled, run_args, session


@pytest.mark.asyncio
@pytest.mark.parametrize('probability,confidence,done', [
    (.77, .69, .06),       # Exact first-choice measurements from public trials.
    (.34, .0, .5),        # Weak but valid argmax; noul is advisory only.
    (.99, .01, .99),      # Goal belief cannot override the chosen action/checks.
    (.79, .59, .01),
])
async def test_valid_argmax_executes_without_probability_or_confidence_gate(enabled, probability, confidence, done):
    backend = FakeBackend()
    tools = session(backend)
    enabled.evaluate.side_effect = [answer(probability=probability, confidence=confidence, done=done),
        answer(choice='handoff', done=.99, options=['handoff', 'observe_again'])]
    try:
        result = await make_jev_browser_tools(tools)[1].ainvoke(run_args())
        assert result['verified'] and result['completed_ids'] == ['go'], result
        assert backend.executions == ['go']
        assert result['judgments'][0]['probability'] == probability
        assert result['judgments'][0]['confidence'] == confidence
    finally:
        await tools.resources.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['handoff', 'observe_again'])
async def test_highest_stop_option_still_hands_back_without_writing(enabled, choice):
    backend = FakeBackend()
    tools = session(backend)
    enabled.evaluate.return_value = answer(choice=choice, probability=.34, confidence=.0, done=.5)
    try:
        result = await make_jev_browser_tools(tools)[1].ainvoke(run_args())
        assert result['reason'] == choice and result['handoff']
        assert not result['executed'] and not result['verified'] and not backend.executions
    finally:
        await tools.resources.aclose()


def test_tool_schema_has_no_legacy_threshold_controls():
    properties = JevRunInput.model_json_schema()['properties']
    assert 'min_probability' not in properties
    assert 'min_confidence' not in properties
    for name in ('min_probability', 'min_confidence'):
        with pytest.raises(ValidationError):
            JevRunInput.model_validate(run_args(**{name: .99}))
