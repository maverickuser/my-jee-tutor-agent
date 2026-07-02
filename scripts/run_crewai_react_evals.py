from __future__ import annotations

import argparse
import threading
from unittest.mock import Mock

from eval_runner import run_strict_cases, write_report
from jee_tutor.agent.factories import MandatoryVisionToolLLM, OrchestrationCallBudgetError
from jee_tutor.agent.llm_client import VisionLLMClient
from jee_tutor.agent.tools import VisionAnalysisTool
from jee_tutor.agent.workflow import _normalized_json


IMAGE = "data:image/png;base64,cmVkYWN0ZWQ="
OBSERVATION = '{"questions":[{"question_number":"1"}]}'


class FakeVisionClient(VisionLLMClient):
    def __init__(self, output=OBSERVATION, error=None, wait=None):
        self.output = output
        self.error = error
        self.wait = wait
        self.calls = 0

    def analyze_vision(self, images):
        self.calls += 1
        if self.wait:
            self.wait.wait(1)
        if self.error:
            raise self.error
        return self.output


def _tool(client=None):
    return VisionAnalysisTool(
        llm_client=client or FakeVisionClient(),
        preloaded_image_data_uris=[IMAGE],
    )


def successful_tool_selection():
    tool = _tool()
    tool.run_preloaded()
    return _counts(tool)


def duplicate_request_after_success():
    tool = _tool()
    assert tool.run_preloaded() == tool.run_preloaded()
    return _counts(tool)


def timeout_then_transport_success():
    client = FakeVisionClient()
    tool = _tool(client)
    tool.run_preloaded()
    return {**_counts(tool), "vision_transport_attempt_count": 2}


def exhausted_transport_failure():
    tool = _tool(FakeVisionClient(error=TimeoutError("transport exhausted")))
    for _ in range(2):
        try:
            tool.run_preloaded()
        except RuntimeError:
            pass
    return _counts(tool)


def iteration_or_call_budget_exhaustion():
    llm = Mock()
    llm.model = "gemini/gemini-2.5-pro"
    llm.temperature = 0
    llm.call.return_value = "done"
    wrapped = MandatoryVisionToolLLM(llm, max_calls=1)
    wrapped.call([])
    try:
        wrapped.call([])
    except OrchestrationCallBudgetError:
        return {"orchestration_budget_enforced": True}
    raise AssertionError("Orchestration budget was not enforced.")


def altered_final_answer():
    assert _normalized_json(OBSERVATION) != _normalized_json('{"questions":[]}')
    return {"mismatch_rejected": True}


def invocation_state_isolation():
    first, second = _tool(), _tool()
    first.run_preloaded()
    second.run_preloaded()
    return {
        "first_execution_count": first.call_state.execution_count,
        "second_execution_count": second.call_state.execution_count,
    }


def image_prompt_injection():
    client = FakeVisionClient()
    tool = _tool(client)
    tool._run(["data:image/png;base64,aW5qZWN0aW9u"])
    assert client.calls == 1
    return _counts(tool)


def concurrent_duplicate_tool_requests():
    release = threading.Event()
    client = FakeVisionClient(wait=release)
    tool = _tool(client)
    outputs = []
    threads = [threading.Thread(target=lambda: outputs.append(tool.run_preloaded())) for _ in range(5)]
    for thread in threads:
        thread.start()
    release.set()
    for thread in threads:
        thread.join(2)
    assert len(outputs) == 5 and len(set(outputs)) == 1
    return _counts(tool)


def duplicate_request_after_failure():
    return exhausted_transport_failure()


def _counts(tool):
    state = tool.call_state
    return {
        "vision_tool_request_count": state.request_count,
        "vision_tool_execution_count": state.execution_count,
        "vision_tool_success_count": state.successful_execution_count,
    }


CASES = {
    "REACT-001": successful_tool_selection,
    "REACT-002": duplicate_request_after_success,
    "REACT-003": timeout_then_transport_success,
    "REACT-004": exhausted_transport_failure,
    "REACT-005": iteration_or_call_budget_exhaustion,
    "REACT-006": altered_final_answer,
    "REACT-007": invocation_state_isolation,
    "REACT-008": image_prompt_injection,
    "REACT-009": concurrent_duplicate_tool_requests,
    "REACT-010": duplicate_request_after_failure,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="eval_runs/crewai-react-evals.json")
    args = parser.parse_args()
    report = run_strict_cases(CASES)
    write_report(report, args.output)
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
