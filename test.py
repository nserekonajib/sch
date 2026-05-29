import os
import uuid
import requests
from dotenv import load_dotenv

load_dotenv()

PAWAPAY_TOKEN = os.getenv("PAWAPAY_TOKEN")

BASE_URL = "https://api.pawapay.io/v2"


class PawaPay:

    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {PAWAPAY_TOKEN}",
            "Content-Type": "application/json"
        }

    def process_payment(self, phone_number, amount):

        payment_id = str(uuid.uuid4())

        payload = {
            "depositId": payment_id,
            "payer": {
                "type": "MMO",
                "accountDetails": {
                    "phoneNumber": phone_number,
                    "provider": "AIRTEL_OAPI_UGA"
                }
            },
            "amount": str(amount),
            "currency": "UGX",
            "clientReferenceId": "INV-123456",
            "customerMessage": "School payment",
            "metadata": [
                {
                    "orderId": "ORD-123456789"
                }
            ]
        }

        print("PAYLOAD:")
        print(payload)

        response = requests.post(
            f"{BASE_URL}/deposits",
            json=payload,
            headers=self.headers
        )

        print("STATUS:", response.status_code)
        print("RESPONSE:", response.text)

        return response.json()


if __name__ == "__main__":

    pawapay = PawaPay()

    result = pawapay.process_payment(
        phone_number="256748675870",
        amount=1000
    )

    print(result)