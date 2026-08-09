from __future__ import annotations

from .ai.client import create_ai_client


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


def generate_explanation(
    query_text: str,
    retrieved_context: str,
) -> dict[str, str]:
    """
    Generate troubleshooting guidance using the currently selected AI server.

    Settings are loaded for every request, so the AI endpoint and model can
    be changed without restarting NOCPilot.
    """

    try:
        client, settings = create_ai_client()

        if settings["use_rag"]:
            context_for_prompt = retrieved_context
        else:
            context_for_prompt = (
                "RAG documentation retrieval is disabled in AI settings."
            )

        user_prompt = f"""
Alert / query:
{query_text}

Retrieved documentation:
{context_for_prompt}
"""

        response = client.chat.completions.create(
            model=settings["model"],
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
        )

        answer = str(
            response.choices[0].message.content or ""
        ).strip()

        if not answer:
            raise RuntimeError(
                "The configured AI model returned an empty response."
            )

    except Exception as error:
        print(
            f"[NOCPilot] AI request failed: {error}"
        )

        answer = (
            "The LLM model is not loaded or could not be contacted."
        )

    return {
        "query": query_text,
        "answer": answer,
    }
