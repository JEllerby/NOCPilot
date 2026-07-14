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
You are a network troubleshooting assistant for NOCPilot.

An alert or error description will be provided along with retrieved network documentation.

Use the retrieved documentation when it is relevant.
If the documentation does not match the vendor, protocol, or issue type, say so clearly.

Always format your response using these exact sections:

Summary:
Give a short explanation of what the alert likely means.

Possible Causes:
- List likely causes as bullet points.

Recommended Actions:
- List clear troubleshooting steps as bullet points.

Ticket Note:
Write a professional ticket note that a NOC analyst could copy into an incident ticket.

Keep the response clear, practical, and focused on network troubleshooting.
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