# pesapal.py - Fixed response handling
import os
import json
import uuid
import requests
import urllib3
from dotenv import load_dotenv

# Load environment variables early
load_dotenv()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class PesaPal:
    def __init__(self):
        self.auth_url = "https://pay.pesapal.com/v3/api/Auth/RequestToken"
        self.api_url = "https://pay.pesapal.com/v3/api/"
        self.token = None

        self.consumer_key = os.getenv("PESAPAL_CONSUMER_KEY")
        self.consumer_secret = os.getenv("PESAPAL_CONSUMER_SECRET")
        self.ipn_url = os.getenv("PESAPAL_IPN_URL", "https://yourdomain.com/ipn")

        # Register IPN only after authentication
        self.ipn_id = None

    def authenticate(self):
        """Authenticate with PesaPal and get access token"""
        try:
            payload = json.dumps({
                "consumer_key": self.consumer_key,
                "consumer_secret": self.consumer_secret
            })
            headers = {
                'Content-Type': 'application/json', 
                'Accept': 'application/json',
                'User-Agent': 'LunserkERP/1.0'
            }

            print("🔄 Authenticating with PesaPal...")
            response = requests.post(
                self.auth_url, 
                headers=headers, 
                data=payload, 
                verify=False,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            # Handle different response formats
            if 'token' in data:
                self.token = data['token']
            elif 'access_token' in data:
                self.token = data['access_token']
            else:
                print(f"❌ Unexpected auth response: {data}")
                return None
                
            print("✅ PesaPal authentication successful")
            
            # Register IPN after getting token
            self.ipn_id = self.register_ipn_url()
            return self.token
            
        except requests.exceptions.RequestException as e:
            print(f"❌ PesaPal authentication failed: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"Response body: {e.response.text}")
            return None
        except Exception as e:
            print(f"❌ Unexpected error during authentication: {e}")
            return None

    def register_ipn_url(self):
        """Register IPN URL with PesaPal"""
        try:
            endpoint = "URLSetup/RegisterIPN"
            payload = json.dumps({
                "url": self.ipn_url, 
                "ipn_notification_type": "GET"
            })
            headers = {
                'Content-Type': 'application/json', 
                'Accept': 'application/json', 
                'Authorization': f"Bearer {self.token}",
                'User-Agent': 'LunserkERP/1.0'
            }
            
            print("🔄 Registering IPN URL...")
            response = requests.post(
                self.api_url + endpoint, 
                headers=headers, 
                data=payload, 
                verify=False,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            ipn_id = data.get('ipn_id') or data.get('Id') or data.get('id')
            print(f"✅ IPN registered successfully: {ipn_id}")
            return ipn_id
            
        except Exception as e:
            print(f"❌ IPN Registration failed: {e}")
            return None

    def submit_order(self, amount, reference_id, callback_url, email, first_name, last_name):
        """Submit order to PesaPal for payment processing"""
        if not self.token:
            if not self.authenticate():
                return None

        try:
            endpoint = "Transactions/SubmitOrderRequest"
            payload = {
                "id": reference_id,
                "currency": "UGX",
                "amount": str(amount),
                "description": "Lunserk ERP Subscription Payment",
                "callback_url": callback_url,
                "notification_id": self.ipn_id,
                "billing_address": {
                    "email_address": email,
                    "phone_number": "",
                    "country_code": "UG",
                    "first_name": first_name[:50],
                    "middle_name": "",
                    "last_name": last_name[:50] if last_name else "User",
                    "line_1": "Lunserk ERP",
                    "line_2": "",
                    "city": "Kampala",
                    "state": "",
                    "postal_code": "",
                    "zip_code": ""
                }
            }
            
            headers = {
                'Content-Type': 'application/json', 
                'Accept': 'application/json', 
                'Authorization': f"Bearer {self.token}",
                'User-Agent': 'LunserkERP/1.0'
            }

            print(f"🔄 Submitting order to PesaPal: UGX {amount}, Ref: {reference_id}")
            response = requests.post(
                self.api_url + endpoint, 
                headers=headers, 
                data=json.dumps(payload), 
                verify=False,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            print(f"✅ Order submission response: {data}")
            
            # Extract order_tracking_id and redirect_url from response
            order_tracking_id = None
            redirect_url = None
            
            # Try different possible field names
            if 'order_tracking_id' in data:
                order_tracking_id = data['order_tracking_id']
            elif 'OrderTrackingId' in data:
                order_tracking_id = data['OrderTrackingId']
            elif 'tracking_id' in data:
                order_tracking_id = data['tracking_id']
            
            if 'redirect_url' in data:
                redirect_url = data['redirect_url']
            elif 'RedirectURL' in data:
                redirect_url = data['RedirectURL']
            elif 'redirect_link' in data:
                redirect_url = data['redirect_link']
            
            # Also check if response is nested
            if not order_tracking_id and 'data' in data:
                order_tracking_id = data['data'].get('order_tracking_id') or data['data'].get('OrderTrackingId')
                redirect_url = data['data'].get('redirect_url') or data['data'].get('RedirectURL')
            
            if order_tracking_id and redirect_url:
                print(f"✅ Order submitted successfully. Tracking ID: {order_tracking_id}")
                return {
                    'order_tracking_id': order_tracking_id,
                    'redirect_url': redirect_url
                }
            else:
                print(f"❌ Missing required fields in response. Got: {data}")
                return None
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Order submission failed: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"Response body: {e.response.text}")
            return None
        except Exception as e:
            print(f"❌ Unexpected error in order submission: {e}")
            import traceback
            traceback.print_exc()
            return None

    def verify_transaction_status(self, order_tracking_id):
        """Verify transaction status with PesaPal"""
        if not self.token:
            if not self.authenticate():
                return None

        try:
            endpoint = f"Transactions/GetTransactionStatus?orderTrackingId={order_tracking_id}"
            headers = {
                'Content-Type': 'application/json', 
                'Accept': 'application/json', 
                'Authorization': f"Bearer {self.token}",
                'User-Agent': 'LunserkERP/1.0'
            }

            print(f"🔄 Verifying transaction status: {order_tracking_id}")
            response = requests.get(
                self.api_url + endpoint, 
                headers=headers, 
                verify=False,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            print(f"✅ Transaction status response: {data}")
            
            # Extract status information
            status_code = data.get('status_code')
            status_map = {
                0: 'INVALID',
                1: 'COMPLETED',
                2: 'FAILED',
                3: 'REVERSED'
            }
            
            result = {
                'status': status_map.get(status_code, 'UNKNOWN'),
                'status_code': status_code,
                'payment_status_description': data.get('payment_status_description'),
                'amount': data.get('amount'),
                'currency': data.get('currency'),
                'created_date': data.get('created_date'),
                'payment_method': data.get('payment_method'),
                'merchant_reference': data.get('merchant_reference')
            }
            
            print(f"✅ Transaction status: {result['status']}")
            return result
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Transaction verification failed: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"Response body: {e.response.text}")
            return None
        except Exception as e:
            print(f"❌ Unexpected error in transaction verification: {e}")
            return None