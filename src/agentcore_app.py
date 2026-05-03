from bedrock_agentcore import BedrockAgentCoreApp

from agentcore_handler import handle_tutor_invocation


app = BedrockAgentCoreApp()


@app.entrypoint
def invoke_tutor(payload: dict, context) -> dict:
    return handle_tutor_invocation(payload)


if __name__ == "__main__":
    app.run()
