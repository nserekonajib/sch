from comms_sdk import CommsSDK, MessagePriority

api_username = "hajaranasejje"
api_key = "b9aa9af77457643f169dd81e3cfe81b172d65fcf2ddfd30d"

sdk = CommsSDK.authenticate(api_username, api_key)

def send_fee_sms(phone, student_name, amount, balance, reciept_url, institution_name):
    message = f"Payment received UGX {amount} for {student_name}. Balance: UGX {balance}. View receipt: {reciept_url}   Thank you for your payment. /n {institution_name} School Fees Payment Confirmation"

    try:
        response = sdk.send_sms(
            [phone],
            message,
            sender_id="SCHOOL",
            priority=MessagePriority.HIGHEST
        )
        return response
    except Exception as e:
        print("SMS Error:", e)
        
