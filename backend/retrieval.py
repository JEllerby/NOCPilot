import chromadb
from sentence_transformers import SentenceTransformer

CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "network_docs"
EMBED_MODEL = "BAAI/bge-base-en-v1.5"

# Load once when FastAPI starts/imports this module
client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client.get_collection(COLLECTION_NAME)
embedder = SentenceTransformer(EMBED_MODEL)


def query_docs(question: str, n_results: int = 3) -> dict:
    """
    Query ChromaDB and return:
    - original query
    - structured matches
    - combined context string for LLM use
    """

    embedding = embedder.encode(question).tolist()

    results = collection.query(
        query_embeddings=[embedding],
        n_results=n_results
    )

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    matches = []
    context_blocks = []

    for i, (doc, metadata) in enumerate(zip(documents, metadatas), start=1):
        source = metadata.get("source", "unknown")
        vendor = metadata.get("vendor", "unknown")
        page = metadata.get("page", "unknown")
        chunk = metadata.get("chunk", "unknown")

        match = {
            "rank": i,
            "source": source,
            "vendor": vendor,
            "page": page,
            "chunk": chunk,
            "document": doc
        }

        matches.append(match)

        context_blocks.append(
            f"[Match {i}] "
            f"Source: {source} | Vendor: {vendor} | "
            f"Page: {page} | Chunk: {chunk}\n{doc}"
        )

    return {
        "query": question,
        "matches": matches,
        "context": "\n\n".join(context_blocks)
    }