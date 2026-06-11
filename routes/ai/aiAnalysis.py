from routes.ai.ai import OpenRouterClient

client = OpenRouterClient()
a = "can you analyse data when given to you "

result = client.chat(a)
print("\nFINAL RESULT:", result)