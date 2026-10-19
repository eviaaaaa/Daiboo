"""Quantized real-service Score shape reproduced over owned loopback HTTP."""
from copy import deepcopy
import pytest
from test.test_typesafe_client import server, STATE, KEY
from utils.typesafe_client import JevClient


@pytest.mark.asyncio
@pytest.mark.parametrize('score,expected', [(0.19, True), (0.18, True), (0.17, True), (0.20, False), (0.16, False)])
async def test_score_quantization_preserves_wire_values_without_renormalization(score, expected):
    levels = ['Not saved with the requested name and plan.',
              'Requested values are entered but not confirmed saved.',
              'Explicitly saved Jev Alice pro status is visible.']
    questions = {'progress': {'type': 'score', 'instructions': 'How far along is saving this profile?', 'criteria': levels}}
    # Exact probability vector observed in the authorized live diagnostic.
    response = {'model': 'jev-1.13.0', 'answers': {'progress': {
        'type': 'score', 'score': score, 'confidence': .73,
        'legend': {str(i): value for i, value in enumerate(levels)},
        'probabilities': {'0': .8200000000000001, '1': .18, '2': .0}}},
        'usage': {'input_tokens': 494, 'output_tokens': 64}}
    original = deepcopy(response)
    with server(body=response) as (url, records, _):
        client = JevClient(api_key=KEY, base_url=url)
        try:
            result = await client.evaluate(state=STATE, questions=questions)
        finally:
            await client.aclose()
    assert result['ok'] is expected
    if expected:
        assert result['answers']['progress']['score'] == score
        assert result['answers']['progress']['probabilities'] == original['answers']['progress']['probabilities']
    else:
        assert result['reason'] == 'invalid_response'
    assert len(records) == 1
