import requests

url = "https://api.pawapay.io/v2/payouts"
payload = {
    "payoutId": "f4401bd2-1568-4140-bf2d-eb77d2b2b639",
    "recipient": {
        "type": "MMO",
        "accountDetails": {
            "phoneNumber": "256763456789",
            "provider": "MTN_MOMO_UGA"
        }
    },
    "amount": "1000",
    "currency": "UGX",
    "clientReferenceId": "INV-123456",
    "customerMessage": "Note of 4 to 22 chars",
    "metadata": [
        {"orderId": "ORD-123456789"},
        {"customerId": "customer@email.com", "isPII": True}
    ]
}

token = 'eyJraWQiOiIxIiwiYWxnIjoiRVMyNTYifQ.eyJ0dCI6IkFBVCIsInN1YiI6IjIxODQxIiwibWF2IjoiMSIsImV4cCI6MjA5NjA5MDM3NSwiaWF0IjoxNzgwNDcxMTc1LCJwbSI6IkRBRixQQUYiLCJqdGkiOiI1M2E5ODUyNi1kNmQxLTQzYzMtYjhlNS0xNTU1ZTkwNjc4MGEifQ.jERnjAzboMBVMANVm6mCu5bPVP0aNDyF0gDco-8ZaQJ-qD9fOdW84mXcc2uVIjcLS1LAQYlV2Fk2spKWQL0hmA'
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

response = requests.post(url, json=payload, headers=headers)

print(response.text)