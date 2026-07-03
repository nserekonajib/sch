/**
 * Student Report Card PDF API
 * --------------------------------------------------
 * POST /generate-report-cards
 *   Accepts JSON describing a school + a list of students (each with
 *   already-computed subject scores, position, aggregates, comments etc.)
 *   and streams back a single PDF containing one professionally designed
 *   report card per student.
 *
 * POST /generate-report-card
 *   Same as above, but expects a single student object instead of a list.
 *
 * POST /generate-competency-report-cards
 *   Generates competency-based curriculum (CBC) report cards.
 *   Expects competency-specific fields: assessments, weightedColumns,
 *   gradeScale, keyTerms, resultDefinitions.
 *
 * POST /generate-competency-report-card
 *   Same as above, but for a single student.
 *
 * GET /health
 *   Simple healthcheck.
 *
 * --------------------------------------------------
 * REPORT TYPE DETECTION:
 * - If payload has 'assessments' field → competency-based report
 * - If payload has 'exams' field → standard exam-based report
 */

const express = require('express');
const { buildReportCardsPdf } = require('./lib/pdfBuilder');
const { buildCompetencyReportCardsPdf } = require('./lib/competencyPdfBuilder');

const app = express();

// Allow generously sized JSON bodies (many students + remote image URLs).
app.use(express.json({ limit: '25mb' }));

app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'report-card-api', time: new Date().toISOString() });
});

/**
 * Shared handler for standard exam-based report cards
 */
async function handleGenerateStandard(req, res, students) {
  try {
    const { school, term, exams } = req.body;

    if (!school || !school.name) {
      return res.status(400).json({ error: 'Missing required field: school.name' });
    }
    if (!Array.isArray(students) || students.length === 0) {
      return res.status(400).json({ error: 'No student data provided' });
    }

    const pdfBuffer = await buildReportCardsPdf({
      school,
      term: term || {},
      exams: Array.isArray(exams) && exams.length ? exams : ['EXAM'],
      students,
    });

    res.set({
      'Content-Type': 'application/pdf',
      'Content-Disposition': `attachment; filename="report-cards-${Date.now()}.pdf"`,
      'Content-Length': pdfBuffer.length,
    });
    res.status(200).send(pdfBuffer);
  } catch (err) {
    console.error('Failed to generate standard report card PDF:', err);
    res.status(500).json({ error: 'Failed to generate report card PDF', detail: err.message });
  }
}

/**
 * Shared handler for competency-based (CBC) report cards
 */
async function handleGenerateCompetency(req, res, students) {
  try {
    const { 
      school, 
      term, 
      assessments, 
      weightedColumns, 
      gradeScale, 
      keyTerms, 
      resultDefinitions 
    } = req.body;

    if (!school || !school.name) {
      return res.status(400).json({ error: 'Missing required field: school.name' });
    }
    if (!Array.isArray(students) || students.length === 0) {
      return res.status(400).json({ error: 'No student data provided' });
    }
    if (!Array.isArray(assessments) || assessments.length === 0) {
      return res.status(400).json({ error: 'Missing required field: assessments' });
    }

    const pdfBuffer = await buildCompetencyReportCardsPdf({
      school,
      term: term || {},
      assessments,
      weightedColumns: weightedColumns || [],
      gradeScale: gradeScale || [],
      keyTerms: keyTerms || [],
      resultDefinitions: resultDefinitions || [],
      students,
    });

    res.set({
      'Content-Type': 'application/pdf',
      'Content-Disposition': `attachment; filename="competency-report-cards-${Date.now()}.pdf"`,
      'Content-Length': pdfBuffer.length,
    });
    res.status(200).send(pdfBuffer);
  } catch (err) {
    console.error('Failed to generate competency report card PDF:', err);
    res.status(500).json({ error: 'Failed to generate competency report card PDF', detail: err.message });
  }
}

/**
 * Detect report type based on payload structure
 * - If 'assessments' exists → competency-based
 * - If 'exams' exists → standard
 * - Default to standard
 */
function detectReportType(body) {
  if (body.assessments && Array.isArray(body.assessments) && body.assessments.length > 0) {
    return 'competency';
  }
  return 'standard';
}

// ---------------------------------------------------------------------------
// STANDARD EXAM-BASED ENDPOINTS
// ---------------------------------------------------------------------------

// Bulk: { school, term, exams, students: [...] }
app.post('/generate-report-cards', (req, res) => {
  handleGenerateStandard(req, res, req.body.students);
});

// Single: { school, term, exams, student: {...} }
app.post('/generate-report-card', (req, res) => {
  const student = req.body.student;
  handleGenerateStandard(req, res, student ? [student] : []);
});

// ---------------------------------------------------------------------------
// COMPETENCY-BASED (CBC) ENDPOINTS
// ---------------------------------------------------------------------------

// Bulk: { school, term, assessments, weightedColumns, gradeScale, keyTerms, resultDefinitions, students: [...] }
app.post('/generate-competency-report-cards', (req, res) => {
  handleGenerateCompetency(req, res, req.body.students);
});

// Single: { school, term, assessments, weightedColumns, gradeScale, keyTerms, resultDefinitions, student: {...} }
app.post('/generate-competency-report-card', (req, res) => {
  const student = req.body.student;
  handleGenerateCompetency(req, res, student ? [student] : []);
});

// ---------------------------------------------------------------------------
// AUTO-DETECT ENDPOINT (Smart Routing)
// ---------------------------------------------------------------------------

/**
 * POST /generate
 * Automatically detects report type based on payload structure.
 * 
 * For standard reports: include 'exams' field
 * For competency reports: include 'assessments' field
 * 
 * Example standard: { school, term, exams: ["BOT","MID","END"], students: [...] }
 * Example competency: { school, term, assessments: ["A1","A2","A3"], weightedColumns: [...], students: [...] }
 */
app.post('/generate', (req, res) => {
  const reportType = detectReportType(req.body);
  
  if (reportType === 'competency') {
    handleGenerateCompetency(req, res, req.body.students || []);
  } else {
    handleGenerateStandard(req, res, req.body.students || []);
  }
});

// ---------------------------------------------------------------------------
// AUTO-DETECT SINGLE STUDENT ENDPOINT
// ---------------------------------------------------------------------------

/**
 * POST /generate-single
 * Auto-detects report type for single student.
 * 
 * Example standard: { school, term, exams: ["BOT","MID","END"], student: {...} }
 * Example competency: { school, term, assessments: ["A1","A2","A3"], student: {...} }
 */
app.post('/generate-single', (req, res) => {
  const reportType = detectReportType(req.body);
  const student = req.body.student;
  
  if (!student) {
    return res.status(400).json({ error: 'Missing required field: student' });
  }
  
  if (reportType === 'competency') {
    handleGenerateCompetency(req, res, [student]);
  } else {
    handleGenerateStandard(req, res, [student]);
  }
});

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => {
  console.log(`Report card API listening on http://localhost:${PORT}`);
  console.log('  Standard endpoints:');
  console.log('    POST /generate-report-cards');
  console.log('    POST /generate-report-card');
  console.log('  Competency endpoints:');
  console.log('    POST /generate-competency-report-cards');
  console.log('    POST /generate-competency-report-card');
  console.log('  Auto-detect endpoints:');
  console.log('    POST /generate (bulk)');
  console.log('    POST /generate-single (single)');
});

module.exports = app;