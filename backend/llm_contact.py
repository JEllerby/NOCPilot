from openai import OpenAI

""" When calling generate_explanation use the following format:

    llm_result = generate_explanation(
        query_text=retrieval_result["query"],
        retrieved_context=retrieval_result["context"]
    )

    This assumes that the output of retrieval.py has been returned as a
    dictionary with the keys query and context.
"""

client = OpenAI(
    base_url="http://25.5.202.103:1234/v1",
    api_key="unused"
)


SYSTEM_PROMPT = """
You are a network troubleshooting assistant.
An error or alert description will be provided with retrieved documentation.
Use the documentation when it is relevant.
If the documentation does not match the vendor, protocol, or issue type, say so clearly.
"""


def generate_explanation(query_text: str, retrieved_context: str) -> dict:
    user_prompt = f"""
Alert / query:
{query_text}

Retrieved documentation:
{retrieved_context}
"""

    try:
        response = client.chat.completions.create(
            model="qwen/qwen3-8b",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ]
        )

        answer = response.choices[0].message.content

    except Exception:
        answer = "The LLM model is not loaded or could not be contacted."

    return {
        "query": query_text,
        "answer": answer
    }