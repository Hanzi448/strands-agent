import os
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from strands.experimental.bidi import BidiAgent
from strands.experimental.bidi.models import BidiNovaSonicModel
from strands.experimental.bidi.tools import stop_conversation
from strands import tool

# Environment configuration
MODEL_ID = os.getenv("MODEL_ID", "amazon.nova-2-sonic-v1:0")
REGION = os.getenv("AWS_REGION", "us-east-1")
# BEDROCK_REGION controls where Nova Sonic model calls are made.
# Defaults to us-east-1. Nova Sonic is only available in select regions.
# See: https://docs.aws.amazon.com/bedrock/latest/userguide/models-regions.html
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-east-1")
INPUT_SAMPLE_RATE = int(os.getenv("INPUT_SAMPLE_RATE", "16000"))
OUTPUT_SAMPLE_RATE = int(os.getenv("OUTPUT_SAMPLE_RATE", "16000"))
CHANNELS = int(os.getenv("CHANNELS", "1"))
FORMAT = os.getenv("FORMAT", "pcm")

# Create FastAPI app
app = FastAPI()

# Create custom tools
@tool
def calculate_expression(expression: str) -> str:
    """
    Evaluate a mathematical expression.
    
    Args:
        expression: A mathematical expression to evaluate (e.g., "2+2", "10*5")
    
    Returns:
        The result of the calculation
    """
    try:
        # Safe evaluation of mathematical expressions using ast
        import ast
        import operator
        
        # Supported operators
        operators = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.USub: operator.neg,
        }
        
        def eval_expr(node):
            if isinstance(node, ast.Num):
                return node.n
            elif isinstance(node, ast.BinOp):
                return operators[type(node.op)](eval_expr(node.left), eval_expr(node.right))
            elif isinstance(node, ast.UnaryOp):
                return operators[type(node.op)](eval_expr(node.operand))
            else:
                raise ValueError(f"Unsupported operation: {type(node).__name__}")
        
        tree = ast.parse(expression, mode='eval')
        result = eval_expr(tree.body)
        return f"The result is: {result}"
    except Exception as e:
        return f"Error calculating: {str(e)}"

@tool
def get_weather() -> str:
    """Get the current weather. Always returns sunny weather."""
    return "It's sunny and 72°F today!"

# Configure Nova Sonic model
sonic_model = BidiNovaSonicModel(
    model_id=MODEL_ID,
    provider_config={
        "audio": {
            "voice": "tiffany",  # Options: "tiffany" or "matthew"
            "input_rate": INPUT_SAMPLE_RATE,
            "output_rate": OUTPUT_SAMPLE_RATE,
            "channels": CHANNELS,
            "format": FORMAT
        },
        # Additional inference parameters can be added here
        # https://docs.aws.amazon.com/nova/latest/userguide/input-events.html
        "inference": {}
    },
    client_config={
        "region": BEDROCK_REGION
    },
)

# Health check endpoint (required by AgentCore)
@app.get("/ping")
async def ping():
    """Health check endpoint for AgentCore Runtime"""
    return {"status": "Healthy", "time_of_last_update": int(datetime.now().timestamp())}

# WebSocket endpoint for bidirectional voice chat
@app.websocket("/ws")
async def voice_chat(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for bidirectional voice streaming.
    
    This endpoint:
    1. Accepts WebSocket connections
    2. Creates a BidiAgent with Nova Sonic model
    3. Streams audio/text input from client
    4. Streams audio/text output back to client
    5. Supports tool execution (calculator, weather)
    6. Handles interruptions (barge-in)
    """
    # Create a new agent instance for this connection
    voice_agent = BidiAgent(
        model=sonic_model,
        tools=[calculate_expression, get_weather, stop_conversation],
        system_prompt="You are a helpful voice assistant with access to tools for calculations and weather information. Keep your responses concise and natural for voice conversation."
    )
    
    try:
        # Accept the WebSocket connection
        await websocket.accept()
        print("WebSocket connection accepted")
        
        # Run the bidirectional agent
        # Strands provides direct WebSocket integration!
        # - websocket.receive_json reads input events from client
        # - websocket.send_json sends output events to client
        await voice_agent.run(
            inputs=[websocket.receive_json],
            outputs=[websocket.send_json]
        )
        
    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"Error in voice chat: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            await websocket.close()
            await voice_agent.stop()
        except Exception as cleanup_error:
            # Log cleanup errors but don't raise to avoid masking original exception
            print(f"Error during cleanup: {cleanup_error}")

# For local development/testing
if __name__ == "__main__":
    import uvicorn
    print(f"Starting voice agent server on port 8080...")
    print(f"Model: {MODEL_ID}")
    print(f"Region: {REGION}")
    print(f"Bedrock Region: {BEDROCK_REGION}")
    print(f"Audio config: {INPUT_SAMPLE_RATE}Hz, {CHANNELS} channel(s), {FORMAT} format")
    
    # Use localhost for local development, 0.0.0.0 only in containerized environments
    host = "0.0.0.0" if os.getenv("CONTAINER_ENV") else "127.0.0.1"
    print(f"Binding to: {host}")
    uvicorn.run(app, host=host, port=8080)
