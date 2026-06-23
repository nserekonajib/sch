from flask import Flask, jsonify, request
from flask_cors import CORS
import smtplib
import threading
import os
import json
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import pytz
from filelock import FileLock

app = Flask(__name__)
CORS(app)

# --- Config ---
email_sender = 'nserekonajib3@gmail.com'
email_password = 'gvai uawu evwn hqfr'  # Use ENV in production
recipients = ['nclenza@gmail.com', 'Bintali613@gmail.com']
wife_name = "Mrs. Nsereko Nabirah"
your_name = "Nsereko Najib"
cycle_length = 26
period_length = 5
uganda_tz = pytz.timezone("Africa/Kampala")
CYCLE_FILE = 'cycle_data.json'
LOCK_FILE = 'cycle_data.lock'

# --- Rate Limiting Config ---
LAST_EMAIL_SENT = {}
EMAIL_INTERVAL_MINUTES = 15  # Cooldown per IP


# --- Rate Limit Checker ---
def can_send_email(ip):
    now = datetime.now()
    last_time = LAST_EMAIL_SENT.get(ip)
    if last_time and (now - last_time).total_seconds() < EMAIL_INTERVAL_MINUTES * 60:
        return False
    LAST_EMAIL_SENT[ip] = now
    return True


# --- File Persistence ---
def load_cycle_data():
    try:
        with FileLock(LOCK_FILE):
            if os.path.exists(CYCLE_FILE):
                with open(CYCLE_FILE, 'r') as f:
                    data = json.load(f)
                    return datetime.fromisoformat(data["last_period_start"])
    except:
        pass
    start = datetime(2025, 7, 22, tzinfo=uganda_tz)
    save_cycle_data(start)
    return start

def save_cycle_data(date):
    try:
        with FileLock(LOCK_FILE):
            with open(CYCLE_FILE, 'w') as f:
                json.dump({"last_period_start": date.isoformat()}, f)
    except:
        pass


# --- Cycle Info Logic ---
def get_current_period_start():
    last_start = load_cycle_data()
    today = datetime.now(uganda_tz)
    while (today - last_start).days >= cycle_length:
        last_start += timedelta(days=cycle_length)
        save_cycle_data(last_start)
    return last_start

def get_cycle_info():
    today = datetime.now(uganda_tz)
    current_start = get_current_period_start()
    days_since = (today - current_start).days
    day_in_cycle = days_since % cycle_length
    days_until_next = cycle_length - day_in_cycle
    fertile_window = range(9, 16)
    is_period = day_in_cycle < period_length
    is_fertile = day_in_cycle in fertile_window

    if is_period:
        status, note = "Menstruation (Period Ongoing)", "We are not having sex today, my soulmate."
    elif is_fertile:
        status, note = "Fertile Day 🌸", "My love, today we can have a baby. Let's make special love."
    else:
        status, note = "Safe Day ✅", "Low chance of pregnancy, but we’re still going to have our special love."

    return {
        "today": today.strftime("%A, %d %B %Y"),
        "day_in_cycle": day_in_cycle + 1,
        "days_until_next": days_until_next,
        "status": status,
        "note": note
    }


# --- Email Creation ---
def create_email_body(info):
    return f"""
    <html><body style="font-family: Arial;">
        <h2>Good Morning {wife_name}, 🌞</h2>
        <p>Here's your menstrual cycle update for <b>{info['today']}</b>:</p>
        <ul>
            <li><b>Day in Cycle:</b> {info['day_in_cycle']} of {cycle_length}</li>
            <li><b>Status:</b> {info['status']}</li>
            <li><b>Message:</b> {info['note']}</li>
            <li><b>Days Remaining to Next Period:</b> {info['days_until_next']}</li>
        </ul>
        <p style="margin-top: 40px;">With all my love ❤️,<br><b>Your loving husband,<br>{your_name}</b></p>
    </body></html>
    """


# --- Background Email with Retry ---
def send_email_with_retries(info, max_retries=2):
    attempt = 0
    while attempt <= max_retries:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "💌 Daily Cycle Update"
            msg["From"] = email_sender
            msg["To"] = ", ".join(recipients)
            msg.attach(MIMEText(create_email_body(info), "html"))

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(email_sender, email_password)
                server.sendmail(email_sender, recipients, msg.as_string())
            print("[EMAIL SENT SUCCESSFULLY]")
            return True
        except Exception as e:
            attempt += 1
            print(f"[EMAIL ATTEMPT {attempt} FAILED]: {e}")
    return False


# --- Flask Endpoint ---
@app.route('/send-cycle-email', methods=['GET'])
def trigger_email():
    client_ip = request.remote_addr
    info = get_cycle_info()

    # Start email sending only if allowed
    if can_send_email(client_ip):
        threading.Thread(target=send_email_with_retries, args=(info,)).start()
        return jsonify({
            "status": "success",
            "message": "Email is being sent. If it fails, we’ll try two more times.",
            "data": info
        })
    else:
        # Email blocked, but data still returned
        return jsonify({
            "status": "partial",
            "message": "Email already sent recently. We'll try again later. Here's your cycle info.",
            "data": info
        })
        
if __name__ == '__main__':
    app.run()

