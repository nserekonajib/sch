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
            print("Warning: OPENROUTER_API_KEY not found in .env file")
            # Don't raise error, just warn

    def chat(self, message, stream=False):
        """
        Send a chat message to OpenRouter API
        
        Args:
            message: The user message to send
            stream: Whether to stream the response
        
        Returns:
            The assistant's response as a string
        """
        if not self.api_key:
            return "⚠️ AI service is not configured. Please add your OpenRouter API key to the .env file (variable: API)."
        
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

        try:
            response = requests.post(
                self.url,
                headers=headers,
                json=payload,
                timeout=60  # Add timeout
            )
            
            # Check if request was successful
            if response.status_code != 200:
                print(f"API Error: {response.status_code} - {response.text[:200]}")
                return f"⚠️ AI service error (Status: {response.status_code}). Please check your API key and try again."
            
            # For streaming response
            if stream:
                return self._handle_stream(response)
            
            # For non-streaming (direct JSON response)
            try:
                result = response.json()
                
                # Check for error in response
                if 'error' in result:
                    error_msg = result['error'].get('message', 'Unknown error')
                    print(f"API Error: {error_msg}")
                    return f"⚠️ AI service error: {error_msg}"
                
                # Extract the message content
                if 'choices' in result and len(result['choices']) > 0:
                    return result['choices'][0]['message']['content']
                else:
                    print(f"Unexpected API response structure: {result.keys()}")
                    return "⚠️ Unable to parse AI response. Please try again."
                    
            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}")
                return "⚠️ Invalid response from AI service. Please try again."
                
        except requests.exceptions.Timeout:
            print("Request timeout")
            return "⚠️ AI service request timed out. Please try again."
        except requests.exceptions.ConnectionError:
            print("Connection error")
            return "⚠️ Cannot connect to AI service. Please check your internet connection."
        except Exception as e:
            print(f"Unexpected error in chat: {e}")
            return f"⚠️ An unexpected error occurred: {str(e)}"

    def _handle_stream(self, response):
        """Handle streaming response from OpenRouter"""
        full_text = ""
        
        try:
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
                        if 'choices' in chunk and len(chunk['choices']) > 0:
                            delta = chunk["choices"][0].get("delta", {}).get("content")
                            if delta:
                                print(delta, end="", flush=True)
                                full_text += delta
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        print(f"Error parsing chunk: {e}")
                        continue

            print()  # newline after stream
            return full_text if full_text else "⚠️ No response received from AI service."
            
        except Exception as e:
            print(f"Error in stream handling: {e}")
            return f"⚠️ Error receiving streaming response: {str(e)}"