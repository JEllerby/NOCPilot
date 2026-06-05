# Nothing happens in line 1

# NOC Pilot document ingestion pipeline for querying the knowledge base documents. 

# Jordan Ellerby, 000526930


'''Currently built to chuck and vectorize .pdf files. Create a ChromaDB database to be able to retrieve
relevant data for entering into a llm prompt. Semantic search rather than basic text matching.
Can convert to handle other files later'''




import os                 # Maybe switch to path instead? 
import fitz
import hashlib
import chromadb

from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter

# --------------------------------------------------
# Environment Variables
# --------------------------------------------------

DOCS_PATH = "./docs"
CHROMA_PATH = "./chroma_db"

COLLECTION_NAME = "network_docs"

EMBED_MODEL = "BAAI/bge-base-en-v1.5"     # There are other models available, will have to test. 
                                           # Should download the model on first run. Will run offline after.
CHUNK_SIZE = 512
CHUNK_OVERLAP = 100

# --------------------------------------------------
# Init
# --------------------------------------------------

client = chromadb.PersistentClient(path=CHROMA_PATH)

collection = client.get_or_create_collection(
    name=COLLECTION_NAME
)

embedder = SentenceTransformer(EMBED_MODEL)

splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP
)

# --------------------------------------------------
# Helpers
# --------------------------------------------------

def file_hash(filepath: str) -> str:
    """Compute SHA256 hash of file for change detection."""
    h = hashlib.sha256()

    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)

    return h.hexdigest()


def extract_pdf_pages(pdf_path):
    """Extract page-level text from PDF."""
    doc = fitz.open(pdf_path)

    pages = []

    for i in range(len(doc)):
        text = doc[i].get_text()

        pages.append({
            "page": i + 1,
            "text": text
        })

    return pages


def delete_existing_document(source_name: str):
    """Remove all chunks for a given document."""
    collection.delete(
        where={"source": source_name}
    )


# --------------------------------------------------
# Ingestion
# --------------------------------------------------

def process_pdf(filename: str):

    path = os.path.join(DOCS_PATH, filename)

    print(f"\nProcessing: {filename}")

    current_hash = file_hash(path)

    # --------------------------------------------------
    # Check existing metadata (idempotency)
    # --------------------------------------------------

    existing = collection.get(
        where={"source": filename},
        include=["metadatas"]
    )

    if existing["metadatas"] and len(existing["metadatas"]) > 0:

        stored_hashes = [
            m.get("file_hash")
            for m in existing["metadatas"]
            if m.get("file_hash")
        ]

        if stored_hashes and stored_hashes[0] == current_hash:
            print("No changes detected — skipping.")
            return

        print("Changes detected — deleting old chunks.")
        delete_existing_document(filename)

    # --------------------------------------------------
    # Extract full document text (IGNORE page boundaries)
    # --------------------------------------------------

    pages = extract_pdf_pages(path)

    full_text = ""
    page_map = []  # optional: track page context

    for page in pages:
        full_text += page["text"] + "\n"
        page_map.append(page["page"])

    # --------------------------------------------------
    # Chunk entire document as ONE text stream
    # --------------------------------------------------

    chunks = splitter.split_text(full_text)

    all_chunks = []
    all_embeddings = []
    all_ids = []
    all_metadata = []

    for i, chunk in enumerate(chunks):

        chunk_id = f"{filename}_c{i}"

        embedding = embedder.encode(chunk).tolist()

        # --------------------------------------------------
        # Metadata (page becomes approximate, not strict)
        # --------------------------------------------------

        metadata = {
            "source": filename,
            "file_hash": current_hash,
            "chunk_index": i
        }

        all_ids.append(chunk_id)
        all_chunks.append(chunk)
        all_embeddings.append(embedding)
        all_metadata.append(metadata)

    # --------------------------------------------------
    # Insert into Chroma
    # --------------------------------------------------

    collection.upsert(
        ids=all_ids,
        documents=all_chunks,
        embeddings=all_embeddings,
        metadatas=all_metadata
    )

    print(f"Inserted {len(all_chunks)} chunks")
    

# --------------------------------------------------
# Cleanup removed files
# --------------------------------------------------

def cleanup_deleted_files():

    print("\nChecking for deleted documents...")

    all_docs = set(os.listdir(DOCS_PATH))

    stored = collection.get(include=["metadatas"])

    seen_sources = set()

    for meta in stored["metadatas"]:
        if meta and "source" in meta:
            seen_sources.add(meta["source"])

    deleted = seen_sources - all_docs

    for doc in deleted:
        print(f"Deleting stale document: {doc}")

        collection.delete(where={"source": doc})


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():

    # Ingest or update documents
    for file in os.listdir(DOCS_PATH):

        if file.lower().endswith(".pdf"):
            process_pdf(file)

    # Remove deleted docs
    cleanup_deleted_files()

    print("\nIngestion complete")


if __name__ == "__main__":
    main()