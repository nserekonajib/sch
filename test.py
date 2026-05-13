import requests

url = "http://localhost:40000/study-resources/api/topics"

payload = {
    "topic_id": 425
}

response = requests.post(url, data=payload)

print(response.status_code)
print(response.json())
