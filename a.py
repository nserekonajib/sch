import requests
import json

url = "https://openrouter.ai/api/v1/chat/completions"

payload = {
    "model": "openrouter/free",
    "messages": [
        {"role": "user", "content": "How many r's are in strawberry?"}
    ],
    "stream": True
}

headers = {
    "Authorization": f"Bearer {API}",
    "Content-Type": "application/json",
}

response = requests.post(url, headers=headers, json=payload, stream=True)

# detect if streaming actually works
if response.headers.get("content-type", "").startswith("text/event-stream"):
    print("Streaming response:\n")

    full_text = ""

    for line in response.iter_lines():
        if not line:
            continue

        line = line.decode("utf-8")

        if line.startswith("data: "):
            data = line.replace("data: ", "")

            if data.strip() == "[DONE]":
                break

            try:
                chunk = json.loads(data)
                delta = chunk["choices"][0]["delta"].get("content")

                if delta:
                    print(delta, end="", flush=True)
                    full_text += delta

            except Exception:
                pass

    print("\n\nDONE")

else:

    data = response.json()

    print("NON-STREAM RESPONSE:\n")

    print(data["choices"][0]["message"]["content"])