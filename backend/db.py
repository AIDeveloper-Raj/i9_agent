import chromadb
from chromadb.utils import embedding_functions
import os
from dotenv import load_dotenv

# 1. Setup paths relative to THIS file's location
# This line finds the directory where db.py lives
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) 

# Now we point to the data folder correctly
# We go "up" one level from backend/ and then into data/
DB_PATH = os.path.join(BASE_DIR, "..", "data", "vector_db")
RULES_FILE = os.path.join(BASE_DIR, "..", "data", "i9_rules.txt")

# Ensure the directories exist
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# 2. Initialize the "Brain Storage" (ChromaDB)
client = chromadb.PersistentClient(path=DB_PATH)

# Load environment variables
load_dotenv()
openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=os.getenv("OPENAI_API_KEY"),
    model_name="text-embedding-3-small"
)

# 3. Create a "Collection"
collection = client.get_or_create_collection(
    name="i9_compliance_rules", 
    embedding_function=openai_ef
)

def ingest_rules():
    """Reads the text file and saves it to the vector database."""
    if not os.path.exists(RULES_FILE):
        print(f"Error: Could not find the file at {RULES_FILE}")
        return

    with open(RULES_FILE, "r") as f:
        text = f.read()

    # Simple chunking: split by paragraphs or double newlines
    chunks = [c.strip() for c in text.split("\n\n") if c.strip()]
    
    if not chunks:
        print("Error: The i9_rules.txt file is empty!")
        return

    # Give each chunk a unique ID
    ids = [f"id_{i}" for i in range(len(chunks))]
    
    # Store them!
    collection.upsert(
        documents=chunks,
        ids=ids
    )
    print(f"Successfully ingested {len(chunks)} rule segments into ChromaDB at {DB_PATH}")

def query_rules(user_query):
    """Finds the most relevant I-9 rules for a user's question."""
    results = collection.query(
        query_texts=[user_query],
        n_results=3
    )
    return results["documents"][0]

if __name__ == "__main__":
    ingest_rules()