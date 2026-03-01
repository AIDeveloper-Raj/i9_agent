# backend/tools.py
import os
import io
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

# 1. Secure file paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "..", "output", "stamped_i9s")

# Use our new "dumb/flattened" template
TEMPLATE_PATH = os.path.join(DATA_DIR, "i9_flat.pdf")

def generate_i9_pdf(employee_data: dict):
    if not os.path.exists(TEMPLATE_PATH):
        return {"error": f"Could not find flattened template at {TEMPLATE_PATH}"}

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    first_name = employee_data.get("first_name", "new")
    last_name = employee_data.get("last_name", "employee")
    output_filepath = os.path.join(OUTPUT_DIR, f"i9_section1_{first_name}_{last_name}.pdf")

    # 2. CREATE THE TRANSPARENT TEXT LAYER
    packet = io.BytesIO()
    # Reportlab uses (X, Y) coordinates starting from the bottom-left corner (0,0)
    can = canvas.Canvas(packet, pagesize=letter)
    can.setFont("Helvetica", 10)

    # --- THE COORDINATE MAPPING ---
    # These are approximate (X, Y) points for Section 1 of the 2023 I-9.
    # We will dial these in perfectly later, but this proves the concept.
    coords = {
        "last_name": (40, 600),
        "first_name": (250, 600),
        "dob": (450, 600),
        "i94_number": (40, 480)
    }

    # Draw the text exactly where it belongs
    for form_key, user_value in employee_data.items():
        if form_key in coords and user_value:
            x, y = coords[form_key]
            can.drawString(x, y, str(user_value))

    can.save()
    packet.seek(0)
    overlay_pdf = PdfReader(packet)

    # 3. MERGE THE LAYER OVER THE TEMPLATE
    template_pdf = PdfReader(TEMPLATE_PATH)
    writer = PdfWriter()

    # Grab Page 1 of the I-9 and stamp our text layer on top
    page1 = template_pdf.pages[0]
    page1.merge_page(overlay_pdf.pages[0])
    writer.add_page(page1)

    # Copy the remaining instruction pages untouched
    for i in range(1, len(template_pdf.pages)):
        writer.add_page(template_pdf.pages[i])

    # 4. Save the legally compliant, flattened result
    with open(output_filepath, "wb") as output_stream:
        writer.write(output_stream)

    return {"success": True, "filepath": output_filepath}