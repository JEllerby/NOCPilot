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
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

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

def get_file_hash(filepath: str) -> str:
    """Compute SHA256 hash of file for change detection."""
    h = hashlib.sha256()

    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)

    return h.hexdigest()


def get_vendor(filepath):

    return os.path.basename(
        os.path.dirname(filepath)
    )


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

def process_pdf(pdf_path):

    filename = os.path.basename(pdf_path)

    source = os.path.relpath(
        pdf_path,
        DOCS_PATH
    )

    vendor = get_vendor(pdf_path)

    file_hash = get_file_hash(pdf_path)


    # Check if document already exists

    existing = collection.get(
        where={
            "source": source
        },
        limit=1
    )


    if existing["metadatas"]:

        old_hash = existing["metadatas"][0].get(
            "file_hash"
        )

        if old_hash == file_hash:
            print(
                f"Skipping {filename} (unchanged)"
            )
            return


        print(
            f"Updating {filename}"
        )

        collection.delete(
            where={
                "source": source
            }
        )


    print(
        f"Ingesting {filename}"
    )


    pages = extract_pdf_pages(pdf_path)


    ids = []
    documents = []
    embeddings = []
    metadatas = []


    for page_data in pages:

        page_num = page_data["page"]
        text = page_data["text"]


        chunks = splitter.split_text(text)


        for index, chunk in enumerate(chunks):

            chunk_id = (
                f"{vendor}_{source}"
                f"_p{page_num}_c{index}"
            )


            ids.append(chunk_id)

            documents.append(chunk)


            embeddings.append(
                embedder.encode(chunk).tolist()
            )


            metadatas.append(
                {
                    "vendor": vendor,
                    "source": source,
                    "page": page_num,
                    "chunk": index,
                    "file_hash": file_hash
                }
            )


    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas
    )


    print(
        f"Added {len(ids)} chunks"
    )


# --------------------------------------------------
# Cleanup removed files
# --------------------------------------------------

def cleanup_deleted_files():

    print("\nChecking for deleted documents...")

    current_files = set()

    for root, dirs, files in os.walk(DOCS_PATH):

        for filename in files:

            if filename.lower().endswith(".pdf"):

                current_files.add(
                    os.path.relpath(
                        os.path.join(root, filename),
                        DOCS_PATH
                    )
                )


    stored = collection.get(
        include=["metadatas"]
    )

    stored_files = {
        meta["source"]
        for meta in stored["metadatas"]
        if meta and "source" in meta
    }


    deleted = stored_files - current_files


    for doc in deleted:

        print(
            f"Deleting stale document: {doc}"
        )

        collection.delete(
            where={
                "source": doc
            }
        )


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():

    # Ingest or update documents
    for root, dirs, files in os.walk(DOCS_PATH):

        for filename in files:

            if filename.lower().endswith(".pdf"):

                filepath = os.path.join(
                    root,
                    filename
                )

                process_pdf(filepath)
                
    # Remove deleted docs
    cleanup_deleted_files()

    print("\nIngestion complete")


if __name__ == "__main__":
    main()