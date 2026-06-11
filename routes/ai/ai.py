import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()


class OpenRouterClient:
    def __init__(self, model="openrouter/free"):
        self.api_key = os.getenv("API")
        self.url = "https://openrouter.ai/api/v1/chat/completions"
        self.model = model

        if not self.api_key:
            raise ValueError("Missing OPENROUTER_API_KEY in .env file")

    def chat(self, message, stream=True):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": message}
            ],
            "stream": stream
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response = requests.post(
            self.url,
            headers=headers,
            json=payload,
            stream=stream
        )

        content_type = response.headers.get("content-type", "")

        # -------------------------
        # STREAM MODE (SSE)
        # -------------------------
        if stream and content_type.startswith("text/event-stream"):
            return self._handle_stream(response)

        # -------------------------
        # FALLBACK MODE
        # -------------------------
        return response.json()["choices"][0]["message"]["content"]

    def _handle_stream(self, response):
        full_text = ""

        for line in response.iter_lines():
            if not line:
                continue

            decoded = line.decode("utf-8")

            if decoded.startswith("data: "):
                data = decoded.replace("data: ", "")

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

        print()  # newline after stream
        return full_text