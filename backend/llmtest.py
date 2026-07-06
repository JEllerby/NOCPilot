from retrieval import query_docs
from llm_contact import generate_explanation


def main():
    device_input = input("Device: ").strip()
    error_input = input("Error: ").strip()

    query_text = (
        f"The device {device_input} has given the error: {error_input}"
    )

    print("\n=== QUERY ===")
    print(query_text)

    retrieval_result = query_docs(query_text)

    print("\n=== RETRIEVED DOCUMENTS ===\n")

    if not retrieval_result["matches"]:
        print("No document matches found.")
    else:
        for match in retrieval_result["matches"]:
            print(
                f"[Rank {match['rank']}] "
                f"Source: {match['source']} | "
                f"Vendor: {match['vendor']} | "
                f"Page: {match['page']} | "
                f"Chunk: {match['chunk']}"
            )
            print(match["document"][:800])
            print("-" * 80)

    print("\n=== LLM RESPONSE ===\n")

    llm_result = generate_explanation(
        query_text=retrieval_result["query"],
        retrieved_context=retrieval_result["context"]
    )

    print(llm_result["answer"])


if __name__ == "__main__":
    main()