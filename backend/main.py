# backend/main.py
import json
import os
from typing import List, Dict
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import openai
from dotenv import load_dotenv

# Import our Enterprise State Models and Enforcer
from backend.models import I9State, StateDeltaPayload, EmployerContext, EmployeeProfile
from backend.state_machine import apply_state_delta
from backend import prompts

load_dotenv()

app = FastAPI(title="CEIPAL I-9 Compliance Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = openai.AsyncClient(api_key=os.getenv("OPENAI_API_KEY"))

ACTIVE_SESSIONS: Dict[str, I9State] = {}

class MessageItem(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    session_id: str = "default_session"
    message: str | None = None
    history: List[MessageItem] = []

def generate_strict_schema(state: I9State) -> dict:
    """The Python backend alone decides what the UI looks like."""
    fields = [
        {"name": "first_name", "label": "Legal First Name", "type": "text", "required": True, "value": state.employee.first_name},
        {"name": "last_name", "label": "Legal Last Name", "type": "text", "required": True, "value": state.employee.last_name},
        {"name": "dob", "label": "Date of Birth", "type": "date", "required": True},
    ]

    instructions = f"Based on your status as '{state.citizenship_status}', please provide the required information below."

    # E-Verify SSN enforcement
    if state.employer.uses_everify:
        fields.append({"name": "ssn", "label": "Social Security Number (Required for E-Verify)", "type": "text", "required": True})

    if state.requires_alien_number and not state.alien_identifier_options:
        fields.append({"name": "alien_number", "label": "Alien Registration Number (A-Number)", "type": "text", "required": True})
        
    if state.requires_uscis_number:
        fields.append({"name": "uscis_number", "label": "USCIS Number", "type": "text", "required": True})

    if state.requires_expiration_date:
        fields.append({"name": "work_auth_expiration", "label": "Work Authorization Expiration Date", "type": "date", "required": False})

    if state.alien_identifier_options:
        instructions += " You must provide exactly ONE of the following identifiers:"
        fields.extend([
            {"name": "opt_alien_number", "label": "Option 1: Alien Registration Number (A-Number)", "type": "text", "required": False},
            {"name": "opt_i94_number", "label": "Option 2: Form I-94 Admission Number", "type": "text", "required": False},
            {"name": "opt_passport_number", "label": "Option 3: Foreign Passport Number", "type": "text", "required": False},
        ])

    return {
        "title": f"I-9 Section 1 (Form Edition: {state.form_edition})",
        "instructions": instructions,
        "fields": fields
    }

@app.post("/api/chat/employee")
async def chat_employee(request: ChatRequest):
    user_message = request.message or ""
    session_id = request.session_id

    # Simulate HR pre-loading data when a new session starts
    if session_id not in ACTIVE_SESSIONS:
        new_session = I9State()
        new_session.employer = EmployerContext(company_name="CEIPAL Corp", uses_everify=True)
        new_session.employee = EmployeeProfile(first_name="Rajesh", preloaded_status="H-1B", section1_due_date="EOD Today")
        # Run gap engine immediately on the pre-loaded data
        from backend.compliance_matrix import evaluate_compliance_gaps
        new_session.compliance_gaps = evaluate_compliance_gaps(new_session)
        ACTIVE_SESSIONS[session_id] = new_session
        
    current_state = ACTIVE_SESSIONS[session_id]

    async def event_stream():
        try:
            # ==========================================
            # THE CONSTRAINT-DRIVEN PROMPT INJECTION
            # ==========================================
            dynamic_instructions = f"""
            --- HR RECORDS ---
            Employee Name: {current_state.employee.first_name}
            Employer: {current_state.employer.company_name} (E-Verify Active: {current_state.employer.uses_everify})
            Onboarding Profile: {current_state.employee.preloaded_status}
            Deadline: {current_state.employee.section1_due_date}

            --- COMPLIANCE GAPS (BLOCKING THE FORM) ---
            The deterministic backend requires you to resolve these gaps before the form can open:
            {current_state.compliance_gaps}

            YOUR DIRECTIVES:
            1. If the user's message is "INIT_CONVERSATION", initiate the chat proactively. Greet them warmly by name, mention their employer and deadline, and state their status naturally (e.g., "Our records indicate you are joining us on an H-1B visa."). Ask them to confirm if this is correct.
            2. NEVER use robotic database terms like "pre-loaded status". Speak like a highly professional, polite HR Concierge. 
            3. Include a brief disclaimer in your first message that you are an AI assistant helping them complete Section 1, and that you do not make final legal determinations.
            4. If there are gaps listed above, your ONLY job is to ask a natural question to resolve ONE of those gaps. 
            5. NEVER return a 'FORM_READY' intent. Only return 'STATE_UPDATE' or 'ASK_QUESTION'.
            """

            system_prompt = "\n\n".join([
                prompts.SYSTEM_ROLE,
                dynamic_instructions, # Injected right at the top!
                prompts.IMMIGRATION_CLASSIFICATION_RULES,
                prompts.ANTI_DISCRIMINATION_GUARDRAILS,
                prompts.OUTPUT_FORMAT_CONTRACT
            ])

            state_context = f"\n\nCURRENT BACKEND STATE:\n{current_state.model_dump_json(indent=2)}"
            
            api_messages = [{"role": "system", "content": system_prompt + state_context}]
            for msg in request.history:
                api_messages.append({"role": msg.role, "content": msg.content})
            api_messages.append({"role": "user", "content": user_message})

            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=api_messages,
                response_format={"type": "json_object"},
                temperature=0.0
            )
            
            ai_text = response.choices[0].message.content
            raw_json = json.loads(ai_text)

            payload = StateDeltaPayload(**raw_json)

            new_state = apply_state_delta(
                current_state=current_state, 
                delta=payload.state_delta,
                modified_by="AI_Agent"
            )
            ACTIVE_SESSIONS[session_id] = new_state 

            response_payload = {
                "intent": payload.intent,
                "narration": payload.narration,
                "current_state": new_state.model_dump(mode="json")
            }

            # The Python Bouncer alone decides if the form opens
            if new_state.is_ready_for_form:
                response_payload["intent"] = "FORM_READY"
                response_payload["artifacts"] = {
                    "dynamic_form": generate_strict_schema(new_state)
                }

            yield f"data: {json.dumps({'type': 'result', 'content': response_payload})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': f'Compliance Engine Error: {str(e)}'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")