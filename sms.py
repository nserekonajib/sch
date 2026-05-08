import requests
import hashlib
school_code = "14001"
password = "ba46b319-0ab0-43d2-b509-9d0199f5c6b5"
def test1():
    
    date = "2024-01-15"
    

    hash_input = school_code + date + password
    request_hash = hashlib.md5(hash_input.encode()).hexdigest().upper()

    url = f"https://schoolpay.co.ug/paymentapi/AndroidRS/SyncSchoolTransactions/{school_code}/{date}/{request_hash}"
    response = requests.get(url)
    print(response.json())
    




# =========================
# CONFIGURATION
# =========================

def test2():
  
    from_date = "2024-01-01"
    to_date = "2024-01-31"


    # =========================
    # GENERATE HASH
    # MD5(SchoolCode + FromDate + Password)
    # =========================

    hash_input = school_code + from_date + password

    request_hash = hashlib.md5(
        hash_input.encode()
    ).hexdigest().upper()

    # =========================
    # API URL
    # =========================

    url = (
        f"https://schoolpay.co.ug/paymentapi/"
        f"AndroidRS/SchoolRangeTransactions/"
        f"{school_code}/{from_date}/{to_date}/{request_hash}"
    )

    print("REQUEST URL:")
    print(url)

    # =========================
    # SEND REQUEST
    # =========================

    try:

        response = requests.get(url)

        print("\nSTATUS CODE:")
        print(response.status_code)

        print("\nRESPONSE:")

        try:
            print(json.dumps(response.json(), indent=4))
        except:
            print(response.text)

    except Exception as e:
        print("ERROR:", str(e))
        
import requests
import hashlib
import json

BASE_URL = "https://schoolpay.co.ug/paymentapi/AndroidRS/AdhocPayments"


def generate_hash(school_code, reference, password):
    """
    MD5(SchoolCode + IdentifyingReference + Password)
    """
    raw = f"{school_code}{reference}{password}"
    return hashlib.md5(raw.encode()).hexdigest().upper()


def request_mobile_money_payment(
    school_code: str,
    password: str,
    amount: int,
    external_reference: str,
    phone_number: str,
    first_name: str,
    last_name: str,
    reason: str
):
    """
    Triggers instant mobile money debit request via SchoolPay API
    """

    # 1. Generate authentication hash
    hash_value = generate_hash(school_code, external_reference, password)

    # 2. Build URL
    url = f"{BASE_URL}/Request/{school_code}/{hash_value}"

    # 3. Payload
    payload = {
        "amount": amount,
        "externalReference": external_reference,
        "phoneNumber": phone_number,
        "firstName": first_name,
        "lastName": last_name,
        "reason": reason
    }

    # 4. Send request
    try:
        response = requests.post(url, json=payload)

        try:
            data = response.json()
        except:
            return {
                "error": "Invalid JSON response",
                "raw": response.text,
                "status_code": response.status_code
            }

        return data

    except Exception as e:
        return {
            "error": str(e)
        }
        
result = request_mobile_money_payment(
    school_code="14001",
    password="ba46b319-0ab0-43d2-b509-9d0199f5c6b5",
    amount=10000,
    external_reference="INV-12345",
    phone_number="256748675870",    
    first_name="John",
    last_name="Doe",
    reason="Tuition Fee"
)
print(result)