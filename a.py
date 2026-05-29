import uuid
import time
import requests
from typing import Dict, Optional


class PawaPayPayout:
    """
    Simple pawaPay payout client (Uganda market).
    """

    def __init__(
        self,
        api_token: str,
        sandbox: bool = True,
        timeout: int = 30
    ):
        self.api_token = api_token
        self.timeout = timeout

        if sandbox:
            self.base_url = "https://api.sandbox.pawapay.io/v2"
        else:
            self.base_url = "https://api.pawapay.io/v2"

        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

    def initiate_payout(
        self,
        amount: str,
        currency: str,
        phone_number: str,
        provider: str,
        payout_id: Optional[str] = None
    ) -> Dict:
        """
        Initiate a payout.

        Example (Uganda):
            payout = client.initiate_payout(
                amount="1000",
                currency="UGX",
                phone_number="256783456789",
                provider="MTN_MOMO_UGA"
            )
        """

        if payout_id is None:
            payout_id = str(uuid.uuid4())

        payload = {
            "payoutId": payout_id,
            "amount": amount,
            "currency": currency,
            "recipient": {
                "type": "MMO",
                "accountDetails": {
                    "phoneNumber": phone_number,
                    "provider": provider
                }
            }
        }

        try:
            response = requests.post(
                f"{self.base_url}/payouts",
                json=payload,
                headers=self.headers,
                timeout=self.timeout
            )

            if response.status_code in [200, 201]:
                return {"success": True, "data": response.json()}

            if response.status_code >= 500:
                status_check = self.check_payout_status(payout_id)

                if status_check.get("status") == "FOUND":
                    return {
                        "success": True,
                        "message": "Payout may have been processed.",
                        "data": status_check
                    }

                return {
                    "success": False,
                    "message": "Payout status unknown.",
                    "data": status_check
                }

            return {
                "success": False,
                "status_code": response.status_code,
                "error": response.text
            }

        except requests.RequestException as e:
            status_check = self.check_payout_status(payout_id)
            return {
                "success": False,
                "message": "Network error occurred.",
                "exception": str(e),
                "status_check": status_check
            }

    def check_payout_status(self, payout_id: str) -> Dict:
        try:
            response = requests.get(
                f"{self.base_url}/payouts/{payout_id}",
                headers=self.headers,
                timeout=self.timeout
            )

            if response.status_code == 200:
                return response.json()

            return {
                "status": "ERROR",
                "status_code": response.status_code,
                "response": response.text
            }

        except requests.RequestException as e:
            return {"status": "ERROR", "message": str(e)}

    def wait_for_completion(
        self,
        payout_id: str,
        interval: int = 5,
        timeout: int = 120
    ) -> Dict:
        final_statuses = {"COMPLETED", "FAILED", "REJECTED"}
        start = time.time()

        while True:
            result = self.check_payout_status(payout_id)

            if result.get("status") == "FOUND":
                payout_data = result.get("data", {})
                payout_status = payout_data.get("status")
                print(f"Current status: {payout_status}")

                if payout_status in final_statuses:
                    return payout_data

            if time.time() - start > timeout:
                return {
                    "status": "TIMEOUT",
                    "message": "Payout still processing."
                }

            time.sleep(interval)

    def validate_phone_number(self, phone_number: str) -> Dict:
        payload = {"phoneNumber": phone_number}

        try:
            response = requests.post(
                f"{self.base_url}/predict-provider",
                json=payload,
                headers=self.headers,
                timeout=self.timeout
            )

            if response.status_code == 200:
                return response.json()

            return {"status": "ERROR", "response": response.text}

        except requests.RequestException as e:
            return {"status": "ERROR", "message": str(e)}


# =========================
# Example Usage (Uganda)
# =========================

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    API_TOKEN = os.getenv("PAWAPAY_TOKEN")

    client = PawaPayPayout(api_token=API_TOKEN, sandbox=True)

    # Validate a Ugandan number (country code 256)
    validation = client.validate_phone_number("2567")
    print("Validation Result:")
    print(validation)

    # Initiate a UGX payout via MTN Uganda
    # Use AIRTEL_OAPI_UGA for Airtel Uganda
    payout = client.initiate_payout(
        amount="1000",
        currency="UGX",
        phone_number="256760671063",
        provider="MTN_MOMO_UGA"
    )

    print("\nPayout Response:")
    print(payout)

    if payout["success"]:
        payout_id = payout["data"]["payoutId"]
        final_status = client.wait_for_completion(payout_id=payout_id)
        print("\nFinal Status:")
        print(final_status)