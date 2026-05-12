from bedrock_agentcore import BedrockAgentCoreApp

from jee_tutor.handler import handle_tutor_invocation


app = BedrockAgentCoreApp()


@app.entrypoint
def invoke_tutor(payload: dict, context) -> dict:
    return handle_tutor_invocation(payload)
