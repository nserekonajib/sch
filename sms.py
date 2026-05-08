import requests
import hashlib
school_code = "14001"
password = "ba46b319-0ab0-43d2-b509-9d0199f5c6b5"
def fun1():
    
    date = "2024-01-15"
    

    hash_input = school_code + date + password
    request_hash = hashlib.md5(hash_input.encode()).hexdigest().upper()

    url = f"https://schoolpay.co.ug/paymentapi/AndroidRS/SyncSchoolTransactions/{school_code}/{date}/{request_hash}"
    response = requests.get(url)
    print(response.json())
    




# =========================
# CONFIGURATION
# =========================

def fun2():
  
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
 