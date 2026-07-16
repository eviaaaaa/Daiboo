import json
import shutil
import subprocess
from pathlib import Path

import pytest


STREAMING_JS = Path(__file__).resolve().parents[1] / "frontend" / "app_utils.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend behavior tests")
def test_ndjson_parser_preserves_events_split_across_network_chunks():
    script = f"""
const {{ createNdjsonParser }} = require({json.dumps(str(STREAMING_JS))});
const events = [];
const parser = createNdjsonParser(event => events.push(event));
parser.push('{{\"type\":\"message\",\"content\":\"hel');
parser.push('lo\"}}\\n{{\"type\":\"tool\",\"content\":\"done\"}}');
parser.finish();
process.stdout.write(JSON.stringify(events));
"""
    completed = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)

    assert json.loads(completed.stdout) == [
        {"type": "message", "content": "hello"},
        {"type": "tool", "content": "done"},
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend behavior tests")
def test_ndjson_parser_ignores_blank_lines_and_reports_invalid_json():
    script = f"""
const {{ createNdjsonParser }} = require({json.dumps(str(STREAMING_JS))});
const events = [];
const errors = [];
const parser = createNdjsonParser(event => events.push(event), error => errors.push(error.message));
parser.push('\\nnot-json\\n{{\"type\":\"message\",\"content\":\"ok\"}}\\n');
parser.finish();
process.stdout.write(JSON.stringify({{events, errorCount: errors.length}}));
"""
    completed = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)

    assert result["events"] == [{"type": "message", "content": "ok"}]
    assert result["errorCount"] == 1
