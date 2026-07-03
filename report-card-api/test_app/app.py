"""
Flask test harness for the Node.js Report Card API.

Run:
    pip install flask requests --break-system-packages
    python app.py

Then open http://localhost:5000 in your browser.

Buttons:
  - "Generate 10 Student Report Cards" -> builds a sample payload for 10
    students and POSTs it to the Node API's /generate-report-cards endpoint.
  - "Test With One Student"            -> POSTs a single student to
    /generate-report-card.

Both buttons stream the returned PDF straight back to the browser so you can
view/download it immediately.

Set the NODE_API_URL env var if your Node API isn't on localhost:4000.
"""

import os
import random
from flask import Flask, request, Response, render_template_string
import requests

app = Flask(__name__)

NODE_API_URL = os.environ.get("NODE_API_URL", "http://localhost:4000")

# ---------------------------------------------------------------------------
# Sample data generation
# ---------------------------------------------------------------------------

FIRST_NAMES = ["John", "Mary", "Peter", "Grace", "David", "Sarah", "Brian",
               "Joan", "Moses", "Esther", "Daniel", "Patricia"]
LAST_NAMES = ["Okello", "Namutebi", "Ssempala", "Nakato", "Kintu", "Auma",
              "Mugisha", "Akello", "Wasswa", "Nansubuga"]

SUBJECTS = ["Mathematics", "English", "Science", "Social Studies"]
EXAMS = ["BOT", "MID", "END"]

CLASS_TEACHER_COMMENTS = [
    "A brilliant and disciplined learner. Keep it up.",
    "Shows great improvement this term.",
    "Needs to put in more effort in class work.",
    "A hardworking and respectful student.",
]
HEAD_TEACHER_COMMENTS = [
    "Promoted to the next class.",
    "Good performance, well done.",
    "Must improve next term.",
    "Excellent overall result.",
]


def grade_for(avg):
    if avg >= 80:
        return "D1"
    if avg >= 70:
        return "D2"
    if avg >= 60:
        return "C3"
    if avg >= 50:
        return "C4"
    return "P7"


def build_student(i):
    subjects = []
    exam_totals = {e: 0 for e in EXAMS}

    for subj in SUBJECTS:
        scores = {e: random.randint(45, 95) for e in EXAMS}
        for e in EXAMS:
            exam_totals[e] += scores[e]
        avg = sum(scores.values()) / len(scores)
        subjects.append({
            "name": subj,
            "scores": scores,
            "avg": round(avg, 1),
            "grade": grade_for(avg),
            "remarks": random.choice(["Excellent work", "Good effort", "Fair", "Needs improvement"]),
        })

    overall_avg = sum(exam_totals.values()) / (len(EXAMS) * len(SUBJECTS))

    return {
        "name": f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
        "studentId": f"S{1000 + i}",
        "class": random.choice(["P.1", "P.2", "P.3", "P.4", "P.5", "P.6", "P.7"]),
        "gender": random.choice(["Male", "Female"]),
        "division": random.choice(["I", "II", "III"]),
        "position": i + 1,
        "outOf": 10,
        "aggregates": random.randint(4, 36),
        # Real, publicly accessible placeholder photo per student
        "photoUrl": f"https://i.pravatar.cc/300?img={(i % 70) + 1}",
        "subjects": subjects,
        "totals": {
            **exam_totals,
            "avg": round(overall_avg, 1),
            "grade": grade_for(overall_avg),
        },
        "classTeacherComment": random.choice(CLASS_TEACHER_COMMENTS),
        "headTeacherComment": random.choice(HEAD_TEACHER_COMMENTS),
        "requirements": "2 reams of paper, 1 mathematical set, school fees balance UGX 50,000",
    }


def build_payload(num_students):
    return {
        "school": {
            "name": "Lunserk Technologies Academy",
            "tagline": "Nursery and Primary",
            "address": "P.O.BOX 3733 Kampala",
            "phone": "0774567467/0756543",
            "motto": "Foundation for your digital ambitions",
            "logoUrl": "https://placehold.co/200x200/16213e/ffffff/png?text=LTA",
        },
        "term": {
            "termYear": "TERM II 2026",
            "nextTermBegins": "Monday, 7th September 2026",
            "reportTitle": "Termly Progressive Report",
        },
        "exams": EXAMS,
        "students": [build_student(i) for i in range(num_students)],
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Report Card API Tester</title>
  <style>
    body { font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; background:#f4f6fa; margin:0; padding:0; }
    .wrap { max-width: 640px; margin: 60px auto; background:#fff; border-radius:12px; padding:36px 40px; box-shadow:0 6px 24px rgba(20,30,60,.08); }
    h1 { font-size: 22px; color:#16213e; margin-bottom:4px; }
    p.sub { color:#5b6472; margin-top:0; margin-bottom:28px; }
    .btn { display:inline-block; padding:14px 22px; border:none; border-radius:8px; font-size:15px; font-weight:600; cursor:pointer; margin-right:12px; margin-bottom:12px; transition: transform .05s ease; }
    .btn:active { transform: scale(0.98); }
    .btn-primary { background:#16213e; color:#fff; }
    .btn-secondary { background:#b8893f; color:#fff; }
    .btn:disabled { opacity:.6; cursor:not-allowed; }
    .status { margin-top:18px; font-size:14px; color:#5b6472; min-height: 20px; }
    .status.error { color:#b3261e; }
    .status.ok { color:#1c7c3f; }
    .api-url { font-size:12px; color:#8a93a3; margin-top:30px; }
    code { background:#f0f2f7; padding:2px 6px; border-radius:4px; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Report Card API Tester</h1>
    <p class="sub">Sends sample student data to the Node.js report card API and returns the generated PDF.</p>

    <button id="btn10" class="btn btn-primary">Generate 10 Student Report Cards</button>
    <button id="btn1" class="btn btn-secondary">Test With One Student</button>

    <div id="status" class="status"></div>

    <div class="api-url">Node API target: <code>{{ api_url }}</code> (set via <code>NODE_API_URL</code> env var)</div>
  </div>

  <script>
    async function generate(count) {
      const statusEl = document.getElementById('status');
      const btns = document.querySelectorAll('.btn');
      btns.forEach(b => b.disabled = true);
      statusEl.className = 'status';
      statusEl.textContent = `Generating ${count} report card(s)... this can take a few seconds while images are fetched.`;

      try {
        const resp = await fetch(`/run?count=${count}`, { method: 'POST' });
        if (!resp.ok) {
          const errText = await resp.text();
          throw new Error(errText || `Request failed with status ${resp.status}`);
        }
        const blob = await resp.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `report-cards-${count}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.open(url, '_blank');
        statusEl.className = 'status ok';
        statusEl.textContent = `Done. PDF generated for ${count} student(s) and opened in a new tab.`;
      } catch (err) {
        statusEl.className = 'status error';
        statusEl.textContent = 'Error: ' + err.message;
      } finally {
        btns.forEach(b => b.disabled = false);
      }
    }

    document.getElementById('btn10').addEventListener('click', () => generate(10));
    document.getElementById('btn1').addEventListener('click', () => generate(1));
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE_TEMPLATE, api_url=NODE_API_URL)


@app.route("/run", methods=["POST"])
def run():
    count = int(request.args.get("count", 10))
    payload = build_payload(count)

    endpoint = "/generate-report-card" if count == 1 else "/generate-report-cards"
    body = {**payload, "student": payload["students"][0]} if count == 1 else payload

    try:
        resp = requests.post(f"{NODE_API_URL}{endpoint}", json=body, timeout=120)
    except requests.exceptions.RequestException as e:
        return Response(f"Could not reach Node API at {NODE_API_URL}: {e}", status=502)

    if resp.status_code != 200:
        return Response(f"Node API error ({resp.status_code}): {resp.text}", status=502)

    return Response(
        resp.content,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'inline; filename="report-cards-{count}.pdf"'},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
