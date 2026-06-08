# Nothing happens in line one 

import chromadb
from sentence_transformers import SentenceTransformer

CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "network_docs"

client = chromadb.PersistentClient(
    path=CHROMA_PATH
)

collection = client.get_collection(
    COLLECTION_NAME
)

embedder = SentenceTransformer(
    "BAAI/bge-base-en-v1.5"
)

while True:

    question = input("\nQuestion: ")

    embedding = embedder.encode(
        question
    ).tolist()

    results = collection.query(
        query_embeddings=[embedding],
        n_results=5
    )

    print("\nTop Matches:\n")

    for doc, metadata in zip(
        results["documents"][0],
        results["metadatas"][0]
    ):

        print(
            f"Source: {metadata['source']} "
            f"Chunk: {metadata['chunk_index']}"
        )

        print(doc[:500])
        print("-" * 80)