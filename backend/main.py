# backend/main.py
import json
import os
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import openai
from dotenv import load_dotenv

# Import our custom modules from the backend folder
from backend.db import query_rules
from backend.prompts import EMPLOYEE_SYSTEM_PROMPT

# Load environment variables (Make sure OPENAI_API_KEY is in your .env file)
load_dotenv()

# 1. Initialize the FastAPI app (The Traffic Cop)
app = FastAPI(title="I-9 Compliance Agent")

# Allow the frontend to securely talk to this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the OpenAI Client
client = openai.AsyncClient(api_key=os.getenv("OPENAI_API_KEY"))

# Define what an incoming chat message looks like
class ChatRequest(BaseModel):
    # Python 3.12 syntax: Accept either format safely
    message: str | None = None
    prompt: str | None = None

# 2. The Employee Chat Endpoint
@app.post("/api/chat/employee")
async def chat_employee(request: ChatRequest):
    # 1. Grab the text whether it came from the new UI ('message') or FiAi UI ('prompt')
    user_message = request.prompt or request.message or ""

    # 2. We move everything INSIDE the stream function. 
    # Now, if anything breaks, the error goes to the chat window instead of spinning forever.
    async def event_stream():
        try:
            # Ask the Brain (ChromaDB)
            relevant_rules_list = query_rules(user_message)
            context_text = "\n\n".join(relevant_rules_list) if isinstance(relevant_rules_list, list) else relevant_rules_list

            # Prepare the Prompt
            system_prompt = EMPLOYEE_SYSTEM_PROMPT.format(context=context_text)

            # Call ChatGPT
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            ai_response_text = response.choices[0].message.content
            ai_json = json.loads(ai_response_text)

            yield f"data: {json.dumps({'type': 'result', 'content': ai_json})}\n\n"

        except Exception as e:
            # Safely push any backend errors directly to your frontend UI
            yield f"data: {json.dumps({'type': 'error', 'content': f'Backend Error: {str(e)}'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

# 3. Serve the Frontend Files
# This automatically mounts your HTML/CSS/JS so you don't need a separate web server
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

if os.path.exists(FRONTEND_DIR):
    # This means going to http://localhost:8000/finance.html will load your UI!
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")