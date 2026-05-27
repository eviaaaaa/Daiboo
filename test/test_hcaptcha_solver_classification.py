from tools.hcaptcha_solver_tool import _classify_solver_exception, default_cdp_endpoint


def test_hcaptcha_default_cdp_endpoint_follows_debugging_port(monkeypatch):
    monkeypatch.setenv("DEBUGGING_PORT", "9333")
    monkeypatch.delenv("BROWSER_CDP_ENDPOINT", raising=False)

    assert default_cdp_endpoint() == "http://127.0.0.1:9333"


def test_hcaptcha_default_cdp_endpoint_treats_blank_override_as_unset(monkeypatch):
    monkeypatch.setenv("BROWSER_CDP_ENDPOINT", "   ")
    monkeypatch.setenv("DEBUGGING_PORT", "9444")

    assert default_cdp_endpoint() == "http://127.0.0.1:9444"


def test_classify_validation_error_as_non_retryable_schema_mismatch():
    code, retryable = _classify_solver_exception(
        Exception("RetryError[ValidationError: challenge_type input should be image_drag_multi]")
    )
    assert code == "solver_schema_mismatch"
    assert retryable is False


def test_classify_missing_challenge_frame_as_non_retryable():
    code, retryable = _classify_solver_exception(
        Exception("Cannot find a valid challenge frame")
    )
    assert code == "challenge_frame_not_found"
    assert retryable is False


def test_classify_none_locator_as_non_retryable_internal_state_error():
    code, retryable = _classify_solver_exception(
        Exception("'NoneType' object has no attribute 'locator'")
    )
    assert code == "solver_internal_frame_state_error"
    assert retryable is False


def test_llm_adapter_alias_normalizes_drag_multiple_to_drag_multi():
    from extensions.llm_adapter import _extract_challenge_type

    assert _extract_challenge_type("image_drag_multiple") == "image_drag_multi"
    assert _extract_challenge_type("image_drag_multi") == "image_drag_multi"


def test_normalize_arrow_text_into_multi_paths():
    """GLM 把 image_drag_drop 答得像 '548,210 -> 350,225; 548,324 -> 298,265'，
    应该归一化成多条 SpatialPath，能直接喂给 ImageDragDropChallenge。"""
    from extensions.llm_adapter import _normalize_drag_drop_payload
    from hcaptcha_challenger.models import ImageDragDropChallenge

    norm = _normalize_drag_drop_payload(
        {"answer": "548,210 -> 350,225; 548,324 -> 298,265"}
    )
    assert norm is not None
    challenge = ImageDragDropChallenge(**norm)
    assert len(challenge.paths) == 2
    assert challenge.paths[0].start_point.x == 548
    assert challenge.paths[1].end_point.y == 265


def test_normalize_draggable_list_into_multi_paths():
    """GLM 偶尔吐 {'draggable': [{'start_x':...,'end_y':...}, ...]}，
    必须能识别这种 flat key 命名并产出合法的 paths。"""
    from extensions.llm_adapter import _normalize_drag_drop_payload
    from hcaptcha_challenger.models import ImageDragDropChallenge

    norm = _normalize_drag_drop_payload(
        {
            "draggable": [
                {"start_x": 100, "start_y": 200, "end_x": 276, "end_y": 275},
                {"start_x": 50, "start_y": 60, "end_x": 70, "end_y": 80},
            ]
        }
    )
    assert norm is not None
    challenge = ImageDragDropChallenge(**norm)
    assert len(challenge.paths) == 2
    assert challenge.paths[0].end_point.x == 276
