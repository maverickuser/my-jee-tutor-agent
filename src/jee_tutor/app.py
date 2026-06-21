import logging
import os

from bedrock_agentcore import BedrockAgentCoreApp

from jee_tutor.handler import handle_tutor_invocation


app = BedrockAgentCoreApp()
logger = logging.getLogger(__name__)


@app.entrypoint
def invoke_tutor(payload: dict, context) -> dict:
    logger.info(
        "agentcore_entrypoint git_sha=%s payload_keys=%s",
        os.getenv("JEE_TUTOR_GIT_SHA", "unknown"),
        sorted(payload.keys()),
    )
    return handle_tutor_invocation(payload)
