# Report Card PDF API

A Node.js/Express API that turns JSON student data into premium, professionally
designed report card PDFs (one PDF, multiple students, one page each).
Includes a Flask test harness so you can generate sample data and try the API
without building a frontend first.

## 1. Node API

```
npm install
npm start          # listens on http://localhost:4000
```

### Endpoints

- `POST /generate-report-cards` — bulk. Body: `{ school, term, exams, students: [...] }`
- `POST /generate-report-card` — single student. Body: `{ school, term, exams, student: {...} }`
- `GET /health` — health check

Both endpoints return `application/pdf` directly (one PDF, one page per student,
auto-paginates a student onto a 2nd page if they have many subjects).

### Request shape

See the big comment block at the top of `server.js` for the full annotated
JSON schema. The short version:

- `school`: name, tagline, address, phone, motto, logoUrl (any direct image URL)
- `term`: termYear, nextTermBegins, reportTitle (all optional, sensible fallbacks)
- `exams`: array of exam labels, e.g. `["BOT","MID","END"]` — works with 1, 2, 3
  or any number of exam columns, the table adapts automatically
- `students[]`: name, studentId, class, gender, division, position, outOf,
  aggregates, photoUrl, subjects[] (name, scores{examLabel: number}, avg, grade,
  remarks), totals{...}, classTeacherComment, headTeacherComment, requirements

All numbers (averages, totals, positions) are expected pre-computed — the API
only handles layout/design, not calculation.

### Images

`school.logoUrl` and `student.photoUrl` are fetched server-side and resized
with `sharp` (logo: contained in a square box; student photo: cropped to a
portrait box) so that report cards stay visually consistent no matter what
size/aspect ratio the source image is. If an image fails to download, a clean
placeholder box is drawn instead — the PDF generation never fails because of
a bad image URL.

## 2. Flask test app

A single-file Flask app (template embedded, no separate HTML files) that:

- Builds a realistic sample payload for 10 students (random names, scores,
  comments, and per-student placeholder avatar photos)
- "Generate 10 Student Report Cards" button → POSTs to `/generate-report-cards`
- "Test With One Student" button → POSTs to `/generate-report-card`
- Streams the returned PDF back and opens it in a new tab

```
cd test_app
pip install flask requests --break-system-packages
python app.py          # http://localhost:5000
```

By default it talks to the Node API at `http://localhost:4000`. Override with:

```
NODE_API_URL=http://your-node-host:4000 python app.py
```

## Design notes

- A4 page, decorative double-border frame, navy/gold premium color palette
- Header: logo (top-left), school name/address/phone (center), student photo
  (top-right) — mirrors the supplied paper template
- 2x4 info grid (Name/ID, Class/Gender, Term-Year/Position, Division/Aggregates)
- Title band, then a fully bordered subjects table with dynamic exam columns,
  zebra striping, and a highlighted TOTALS row
- Class Teacher's / Head Teacher's comment boxes, Requirements box, signature
  lines and motto footer
- If a student has too many subjects to fit one page, the table automatically
  continues onto a second page for that student only — every other student
  stays unaffected
