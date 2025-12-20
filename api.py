import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright
from langchain.messages import HumanMessage, AIMessage
from langgraph.types import Command
import json
import os
import shutil
from pathlib import Path
import asyncio
import sys
import pprint

# Set Windows event loop policy for Playwright
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from utils.my_browser import launch_or_connect_browser
from agent_factory import create_browser_agent, get_agent_tools
from rag.document_rag_pgvector import save_document_to_pgvector

# Global state
class AppState:
    browser = None
    agent = None
    playwright = None

state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Playwright
    print("Initializing Playwright...")
    state.playwright = await async_playwright().start()
    
    # Initialize Browser
    print("Connecting to Browser...")
    # launch_or_connect_browser returns a coroutine when using async playwright
    state.browser = await launch_or_connect_browser(state.playwright)
    
    # Ensure at least one context and page exists
    print("Ensuring browser context and page...")
    contexts = state.browser.contexts
    if not contexts:
        context = await state.browser.new_context()
    else:
        context = contexts[0]
        
    if not context.pages:
        await context.new_page()
    
    # Initialize Agent
    print("Creating Agent...")
    state.agent = create_browser_agent(state.browser)
    
    print("System initialized and ready.")
    yield
    
    # Cleanup
    print("Cleaning up...")
    if state.browser:
        await state.browser.close()
    if state.playwright:
        await state.playwright.stop()

app = FastAPI(lifespan=lifespan, title="NexusSurf API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"

@app.post("/chat")
async def chat(request: ChatRequest):
    async def event_generator():
        config = {"configurable": {"thread_id": request.thread_id}, "recursion_limit": 80}
        
        # Check for existing interrupt state
        snapshot = await state.agent.aget_state(config)
        if snapshot.next:
            # We are in an interrupted state, interpret user input as a decision
            user_input = request.message.strip().lower()
            if user_input in ["approve", "同意", "yes", "y"]:
                payload = {"decisions": [{"type": "approve"}]}
                inputs = Command(resume=payload)
                yield json.dumps({"type": "log", "content": "Resuming with approval..."}, ensure_ascii=False) + "\n"
            elif user_input in ["reject", "拒绝", "no", "n"]:
                # Simple rejection for now, could parse reason
                payload = {"decisions": [{"type": "reject", "message": "User rejected."}]}
                inputs = Command(resume=payload)
                yield json.dumps({"type": "log", "content": "Resuming with rejection..."}, ensure_ascii=False) + "\n"
            else:
                # If user input is not a clear decision, maybe they want to chat? 
                # But we are stuck in interrupt. 
                # For now, let's assume any other input is a rejection or ask for clarification.
                # Or better, treat it as a rejection with the message as reason.
                payload = {"decisions": [{"type": "reject", "message": request.message}]}
                inputs = Command(resume=payload)
                yield json.dumps({"type": "log", "content": f"Resuming with rejection (reason: {request.message})..."}, ensure_ascii=False) + "\n"
        else:
            # Normal chat flow
            inputs = {"messages": [HumanMessage(content=f"用户问题：{request.message}")]}
        
        try:
            async for chunk in state.agent.astream(inputs, config=config, stream_mode="updates"):
                # Filter out unnecessary middleware logs
                keys = list(chunk.keys())
                if len(keys) == 1 and keys[0] in [
                    "ContextManagerMiddleware.before_model",
                    "HumanInTheLoopMiddleware.after_model",
                    "log_response_to_database.after_agent",
                    "log_agent_response.after_agent",
                    "log_agent_start.before_agent"
                ]:
                    continue

                # Analyze chunk to distinguish between logs and actual messages
                is_message = False
                content = pprint.pformat(chunk)
                
                # Check if it's a model response with AIMessage
                if "model" in chunk and "messages" in chunk["model"]:
                    messages = chunk["model"]["messages"]
                    for msg in messages:
                        if isinstance(msg, AIMessage):
                            # Found the agent's response
                            data = json.dumps({"type": "message", "content": msg.content}, ensure_ascii=False)
                            yield f"{data}\n"
                            is_message = True
                
                # If it's not a message (or in addition to it, if we want to log the raw chunk too)
                # For now, if we found a message, we skip sending the raw log to avoid duplication/noise
                # unless it's a tool call or other step.
                
                if not is_message:
                    # Determine log type for better frontend display
                    log_type = "log"
                    if "tools" in chunk:
                        log_type = "tool"
                    
                    # Send as log
                    data = json.dumps({"type": log_type, "content": content}, ensure_ascii=False)
                    yield f"{data}\n"
                
            # Check for interruption
            snapshot = await state.agent.aget_state(config)
            if snapshot.next:
                data = json.dumps({"type": "interrupt", "content": "Task interrupted. Approval needed."}, ensure_ascii=False)
                yield f"{data}\n"
                
        except Exception as e:
            data = json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False)
            yield f"{data}\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

@app.get("/tools")
async def list_tools():
    if not state.browser:
        return []
    tools = get_agent_tools(state.browser)
    return [{"name": t.name, "description": t.description} for t in tools]

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    temp_dir = Path("temp_uploads")
    temp_dir.mkdir(exist_ok=True)
    file_path = temp_dir / file.filename
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Call RAG save function
        # Note: save_document_to_pgvector is synchronous or async?
        # Let's check. It seems synchronous in the file read.
        # If it's sync, we should run it in a thread pool to avoid blocking the event loop.
        # But for simplicity, we'll call it directly if it's fast enough, or use run_in_executor.
        
        await asyncio.to_thread(save_document_to_pgvector, [file_path])
        
        return {"status": "success", "filename": file.filename, "message": "Document indexed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8801)
