/**
 * Competency-Based Curriculum (CBC) Report Card Builder
 * --------------------------------------------------
 * A second, parallel report style — used alongside (not instead of) the
 * standard exam-based report in pdfBuilder.js. This one matches a
 * competency-based grading sheet: per-subject competency assessments
 * (A1..A4, max 4), weighted percentage columns, a grade-scale legend,
 * an overall achievement summary, a "key to terms" legend, result
 * definitions, comments, and a dates/fees footer row.
 *
 * Reuses the shared header/info-grid/title/frame primitives from
 * pdfBuilder.js so both report styles look like they belong to the same
 * system, then adds the competency-specific sections below.
 *
 * --------------------------------------------------
 * LAYOUT GUARANTEE
 * --------------------------------------------------
 * The whole report (header, info grid, title, subject table, grade scale,
 * overall row, key-to-terms, result definitions, comments, footer) is
 * forced onto a SINGLE A4 page, regardless of subject count (tested up to
 * ~12 subjects). This is done by:
 *   1. Reserving fixed heights for every non-table section up front.
 *   2. Giving whatever vertical space remains to the subject table, and
 *      dividing it across the actual number of subject rows (+ header +
 *      averages row), clamped to a sensible min/max row height.
 *   3. Always rendering text with `ellipsis: true` and a fixed cell width
 *      / height so long values are truncated with "…" instead of
 *      overflowing past a column border or wrapping into the next row.
 * No page-break / addPage() calls are used inside a student's report —
 * everything is sized to fit before any drawing happens.
 *
 * --------------------------------------------------
 * EXPECTED JSON SHAPE
 * --------------------------------------------------
 * {
 *   "school": { ...same as pdfBuilder... },
 *   "term": { ...same as pdfBuilder... },
 *   // 1 to 4 competency assessment columns, e.g. ["A1","A2","A3"]
 *   "assessments": ["A1", "A2", "A3"],
 *   // any number of weighted/derived percentage columns, in display order
 *   "weightedColumns": [
 *     { "key": "20%", "label": "20%" },
 *     { "key": "80%", "label": "80%" },
 *     { "key": "100%", "label": "100%" }
 *   ],
 *   // school-wide grading scale legend (same for every student)
 *   "gradeScale": [
 *     { "grade": "A", "range": "100 - 75" },
 *     { "grade": "B", "range": "75 - 60" },
 *     { "grade": "C", "range": "60 - 50" },
 *     { "grade": "D", "range": "50 - 35" },
 *     { "grade": "E", "range": "35 - 0" }
 *   ],
 *   // school-wide legend of abbreviation -> meaning
 *   "keyTerms": [
 *     { "code": "A1", "label": "Average Chapter Assessment" },
 *     { "code": "80%", "label": "End of term assessment" }
 *   ],
 *   // school-wide list of result-category definitions
 *   "resultDefinitions": [
 *     { "label": "Result 1", "text": "The learner sits for minimum 8 subjects..." },
 *     { "label": "Result 2", "text": "The learner sat for less than 8 subjects..." },
 *     { "label": "Result 3", "text": "The learner scores only grade E in the subjects taken" }
 *   ],
 *   "students": [
 *     {
 *       "name": "...", "studentId": "...", "class": "...", "gender": "...",
 *       "division": "...", "position": 1, "outOf": 30, "aggregates": 10,
 *       "photoUrl": "...",
 *       "subjects": [
 *         {
 *           "name": "History & Political",
 *           "scores": { "A1": 3.0 },             // keyed by assessments[]
 *           "avg": 3.0,                           // optional, shown if assessments.length > 1
 *           "weighted": { "20%": 20.0, "80%": 38.0, "100%": 58.0 },
 *           "grade": "C",
 *           "levelOfAchievement": "Satisfactory"
 *         }
 *       ],
 *       "totals": {
 *         "avg": 1.9,
 *         "weighted": { "100%": 45.5 },
 *         "grade": "D",
 *         "result": 1
 *       },
 *       "overall": [
 *         { "label": "Overall Identifier", "value": "1" },
 *         { "label": "Overall Achievement", "value": "Basic" },
 *         { "label": "Overall grade", "value": "D" }
 *       ],
 *       "classTeacherComment": "...",
 *       "headTeacherComment": "...",
 *       "footerFields": [
 *         { "label": "Term Ended On", "value": "22/08/2025" },
 *         { "label": "Next Term Begins", "value": "19/09/2025" },
 *         { "label": "Fees Balance", "value": "" },
 *         { "label": "Fees Next Term", "value": "" },
 *         { "label": "Other Requirement", "value": "" }
 *       ]
 *     }
 *   ]
 * }
 *
 * gradeScale, keyTerms and resultDefinitions are typically the same for the
 * whole school, so they're sent once at the top level rather than repeated
 * per student.
 *
 * NOTE: "code" and "teacherInitials" fields on a subject are still accepted
 * in the input for backwards compatibility, but are no longer rendered —
 * the CODE and TR columns have been removed from the table.
 */

const { fetchAndResizeImage } = require('./imageHelper');
const {
  COLORS, PAGE, MARGIN, CONTENT_WIDTH,
  drawPageFrame, drawHeader, drawInfoGrid, drawTitle,
} = require('./pdfBuilder');
const PDFDocument = require('pdfkit');

const PAGE_BOTTOM = PAGE.height - MARGIN - 14; // hard floor everything must respect

async function buildCompetencyReportCardsPdf({
  school, term, assessments, weightedColumns, gradeScale, keyTerms, resultDefinitions, students,
}) {
  const doc = new PDFDocument({
    size: 'A4',
    margins: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN },
    bufferPages: true,
    autoFirstPage: true,
    info: {
      Title: `${school.name || 'School'} - Competency Report Cards`,
      Author: school.name || 'Report Card System',
    },
  });
  const chunks = [];
  doc.on('data', (c) => chunks.push(c));
  const done = new Promise((resolve, reject) => {
    doc.on('end', () => resolve(Buffer.concat(chunks)));
    doc.on('error', reject);
  });

  const logoBuffer = await fetchAndResizeImage(school.logoUrl, { width: 140, height: 140, fit: 'contain' });
  const safeAssessments = (assessments || []).slice(0, 4); // hard cap A1..A4
  const safeWeighted = weightedColumns || [];

  for (let i = 0; i < students.length; i++) {
    const student = students[i];
    if (i > 0) doc.addPage();

    const photoBuffer = await fetchAndResizeImage(student.photoUrl, { width: 220, height: 260, fit: 'cover' });

    renderCompetencyReportCard(doc, {
      school, term, student, logoBuffer, photoBuffer,
      assessments: safeAssessments,
      weightedColumns: safeWeighted,
      gradeScale: gradeScale || [],
      keyTerms: keyTerms || [],
      resultDefinitions: resultDefinitions || [],
    });
  }

  doc.end();
  return done;
}

// ---------------------------------------------------------------------------
// Single-page layout planner
// ---------------------------------------------------------------------------
// Computes how tall every section is allowed to be so the whole report fits
// in the vertical space left after the header/info-grid/title, for a given
// number of subject rows.
function planLayout(startY, subjectCount, ctx) {
  const GAP = 6;

  // --- Fixed-height sections (compact, professional spacing) ---
  const gradeScaleH = ctx.gradeScale.length ? 18 * 2 : 0; // grade row + range row
  const overallH = ctx.overall.length ? 19 : 0;
  const keyTermsLabelH = 12;
  const keyTermsRowH = ctx.keyTerms.length ? 14 : 0;
  const keyTermsH = ctx.keyTerms.length ? keyTermsLabelH + keyTermsRowH : 0;

  const resultDefRowH = 13;
  const resultDefH = ctx.resultDefinitions.length * resultDefRowH;

  const commentLabelH = 11;
  const commentBoxH = 30;
  const commentsH = (commentLabelH + commentBoxH + GAP) * 2;

  const footerH = ctx.footerFields.length ? 14 * 2 : 0;

  const mottoH = ctx.motto ? 16 : 0;

  const fixedSectionsTotal = gradeScaleH + overallH + keyTermsH + resultDefH + commentsH + footerH + mottoH;
  const sectionGaps = GAP * 6; // gaps between the ~7 stacked sections below the table

  // --- Whatever is left over goes to the subject table ---
  const tableHeaderH = 20;
  const availableForTable = (PAGE_BOTTOM - startY) - fixedSectionsTotal - sectionGaps;
  const rowsNeeded = subjectCount + 1; // +1 averages row
  let tableRowH = Math.floor((availableForTable - tableHeaderH) / Math.max(rowsNeeded, 1));
  // Clamp to a readable but compact range.
  tableRowH = Math.max(11, Math.min(18, tableRowH));

  const tableH = tableHeaderH + tableRowH * rowsNeeded;

  return {
    GAP,
    tableHeaderH,
    tableRowH,
    tableH,
    gradeScaleH,
    overallH,
    keyTermsLabelH,
    keyTermsRowH,
    keyTermsH,
    resultDefRowH,
    resultDefH,
    commentLabelH,
    commentBoxH,
    commentsH,
    footerH,
    mottoH,
  };
}

function renderCompetencyReportCard(doc, ctx) {
  const { student } = ctx;

  drawPageFrame(doc);
  let y = drawHeader(doc, ctx);
  y = drawInfoGrid(doc, ctx, y);
  y = drawTitle(doc, { ...ctx, term: { ...ctx.term, reportTitle: ctx.term.reportTitle || 'COMPETENCY BASED ASSESSMENT REPORT' } }, y);

  const subjects = Array.isArray(student.subjects) ? student.subjects : [];
  const overall = Array.isArray(student.overall) ? student.overall : [];
  const footerFields = Array.isArray(student.footerFields) ? student.footerFields : [];

  const plan = planLayout(y, subjects.length, {
    gradeScale: ctx.gradeScale,
    overall,
    keyTerms: ctx.keyTerms,
    resultDefinitions: ctx.resultDefinitions,
    footerFields,
    motto: ctx.school.motto,
  });

  y = drawCompetencyTable(doc, ctx, y, subjects, plan);
  y += plan.GAP;

  y = drawGradeScale(doc, ctx, y, plan);
  y += plan.GAP;

  y = drawOverallRow(doc, { ...ctx, student: { ...student, overall } }, y, plan);
  y += plan.GAP;

  y = drawKeyTerms(doc, ctx, y, plan);
  y += plan.GAP;

  y = drawResultDefinitions(doc, ctx, y, plan);
  y += plan.GAP;

  y = drawCompetencyComments(doc, ctx, y, plan);
  y += plan.GAP;

  y = drawDatesFooterRow(doc, { ...ctx, student: { ...student, footerFields } }, y, plan);

  if (ctx.school.motto) {
    doc.font('Helvetica-Oblique').fontSize(8.5).fillColor(COLORS.gold)
      .text(`"${ctx.school.motto}"`, MARGIN, PAGE.height - MARGIN - 22, {
        width: CONTENT_WIDTH, align: 'center', height: 14, ellipsis: true,
      });
  }
}

// ---------------------------------------------------------------------------
// Helper: draw text clipped/truncated to a cell so it can never cross a
// column or row border. Always single-line with ellipsis.
// ---------------------------------------------------------------------------
function cellText(doc, val, x, y, w, h, opts = {}) {
  const {
    font = 'Helvetica', size = 7.5, color = COLORS.ink, align = 'center', padX = 3,
  } = opts;
  doc.font(font).fontSize(size).fillColor(color)
    .text(String(val == null || val === '' ? '-' : val), x + padX, y + Math.max(0, (h - size) / 2 - 1), {
      width: Math.max(2, w - padX * 2),
      height: h,
      align,
      ellipsis: true,
      lineBreak: false,
    });
}

// ---------------------------------------------------------------------------
// Section: competency assessment table
// SUBJECT | A1..A4 | [AVG] | weighted cols... | GRADE | LEVEL OF ACHIEVEMENT
// (CODE and TR columns removed)
// ---------------------------------------------------------------------------
function drawCompetencyTable(doc, ctx, startY, subjects, plan) {
  const { assessments, weightedColumns, student } = ctx;
  const showAvg = assessments.length > 1;

  const subjectW = 150;
  const assessW = 26;
  const avgW = showAvg ? 34 : 0;
  const weightedW = 34;
  const gradeW = 40;

  const fixedW = subjectW + avgW + gradeW + weightedColumns.length * weightedW;
  const assessTotalW = assessments.length * assessW;
  const levelW = Math.max(90, CONTENT_WIDTH - fixedW - assessTotalW);

  const headers = ['SUBJECT', ...assessments, ...(showAvg ? ['AVG'] : []),
    ...weightedColumns.map((w) => w.label), 'GRADE', 'LEVEL OF ACHIEVEMENT'];
  const colWidths = [subjectW, ...assessments.map(() => assessW), ...(showAvg ? [avgW] : []),
    ...weightedColumns.map(() => weightedW), gradeW, levelW];

  let y = startY;
  const HEADER_H = plan.tableHeaderH;
  const ROW_H = plan.tableRowH;
  const ROW_FONT = ROW_H >= 15 ? 7.5 : (ROW_H >= 13 ? 7 : 6.5);

  const drawHeaderRow = (yy) => {
    doc.save().rect(MARGIN, yy, CONTENT_WIDTH, HEADER_H).fill(COLORS.navy).restore();
    let x = MARGIN;
    headers.forEach((h, i) => {
      cellText(doc, h.toUpperCase(), x, yy, colWidths[i], HEADER_H, {
        font: 'Helvetica-Bold', size: 7, color: COLORS.white, align: i === 0 ? 'left' : 'center',
      });
      x += colWidths[i];
    });
    doc.save().lineWidth(0.6).strokeColor('#2b3a63');
    x = MARGIN;
    colWidths.forEach((w) => { doc.moveTo(x, yy).lineTo(x, yy + HEADER_H).stroke(); x += w; });
    doc.moveTo(x, yy).lineTo(x, yy + HEADER_H).stroke();
    doc.restore();
    return yy + HEADER_H;
  };

  y = drawHeaderRow(y);

  subjects.forEach((subj, idx) => {
    if (idx % 2 === 1) {
      doc.save().rect(MARGIN, y, CONTENT_WIDTH, ROW_H).fill(COLORS.zebra).restore();
    }

    const rowValues = [
      subj.name || '-',
      ...assessments.map((a) => (subj.scores && subj.scores[a] != null ? Number(subj.scores[a]).toFixed(1) : '-')),
      ...(showAvg ? [subj.avg != null ? Number(subj.avg).toFixed(1) : '-'] : []),
      ...weightedColumns.map((w) => (subj.weighted && subj.weighted[w.key] != null ? Number(subj.weighted[w.key]).toFixed(1) : '-')),
      subj.grade || '-',
      subj.levelOfAchievement || '-',
    ];

    let x = MARGIN;
    rowValues.forEach((val, i) => {
      const isSubject = i === 0;
      cellText(doc, String(val).toUpperCase(), x, y, colWidths[i], ROW_H, {
        font: isSubject ? 'Helvetica-Bold' : 'Helvetica',
        size: ROW_FONT,
        color: COLORS.ink,
        align: isSubject ? 'left' : 'center',
      });
      x += colWidths[i];
    });

    doc.save().lineWidth(0.4).strokeColor(COLORS.rule).rect(MARGIN, y, CONTENT_WIDTH, ROW_H).stroke();
    x = MARGIN;
    colWidths.forEach((w) => { doc.moveTo(x, y).lineTo(x, y + ROW_H).stroke(); x += w; });
    doc.moveTo(x, y).lineTo(x, y + ROW_H).stroke();
    doc.restore();

    y += ROW_H;
  });

  // AVERAGE row
  const totals = student.totals || {};
  doc.save().rect(MARGIN, y, CONTENT_WIDTH, ROW_H).fill('#e9edf5').restore();
  const avgRowValues = [
    'AVG:',
    ...assessments.map(() => ''),
    ...(showAvg ? [totals.avg != null ? Number(totals.avg).toFixed(1) : '-'] : []),
    ...weightedColumns.map((w) => (totals.weighted && totals.weighted[w.key] != null ? Number(totals.weighted[w.key]).toFixed(1) : '-')),
    totals.grade || '-',
    totals.result != null ? `Result ${totals.result}` : '-',
  ];
  let x = MARGIN;
  avgRowValues.forEach((val, i) => {
    cellText(doc, String(val).toUpperCase(), x, y, colWidths[i], ROW_H, {
      font: 'Helvetica-Bold', size: ROW_FONT, color: COLORS.navy, align: i === 0 ? 'left' : 'center',
    });
    x += colWidths[i];
  });
  doc.save().lineWidth(0.7).strokeColor(COLORS.navy).rect(MARGIN, y, CONTENT_WIDTH, ROW_H).stroke();
  x = MARGIN;
  colWidths.forEach((w) => { doc.moveTo(x, y).lineTo(x, y + ROW_H).stroke(); x += w; });
  doc.moveTo(x, y).lineTo(x, y + ROW_H).stroke();
  doc.restore();
  y += ROW_H;

  doc.save().lineWidth(1).strokeColor(COLORS.navy).rect(MARGIN, startY, CONTENT_WIDTH, y - startY).stroke().restore();

  return y;
}

// ---------------------------------------------------------------------------
// Section: grade scale legend (GRADE row + SCORES row)
// ---------------------------------------------------------------------------
function drawGradeScale(doc, ctx, startY, plan) {
  const { gradeScale } = ctx;
  if (!gradeScale.length) return startY;

  const colW = CONTENT_WIDTH / gradeScale.length;
  const rowH = 18;
  let y = startY;

  doc.save().lineWidth(0.7).strokeColor(COLORS.rule);
  let x = MARGIN;
  doc.save().rect(MARGIN, y, CONTENT_WIDTH, rowH).fill(COLORS.navy).restore();
  gradeScale.forEach((g) => {
    doc.rect(x, y, colW, rowH).stroke();
    cellText(doc, `GRADE ${g.grade}`, x, y, colW, rowH, { font: 'Helvetica-Bold', size: 8.5, color: COLORS.white });
    x += colW;
  });
  y += rowH;

  x = MARGIN;
  gradeScale.forEach((g) => {
    doc.rect(x, y, colW, rowH).stroke();
    cellText(doc, g.range || '-', x, y, colW, rowH, { font: 'Helvetica', size: 8, color: COLORS.ink });
    x += colW;
  });
  doc.restore();
  y += rowH;

  return y;
}

// ---------------------------------------------------------------------------
// Section: overall identifier / achievement / grade row
// ---------------------------------------------------------------------------
function drawOverallRow(doc, ctx, startY, plan) {
  const { student } = ctx;
  const pairs = Array.isArray(student.overall) ? student.overall : [];
  if (!pairs.length) return startY;

  const colW = CONTENT_WIDTH / (pairs.length * 2);
  const rowH = plan.overallH;
  let x = MARGIN;
  const y = startY;

  doc.save().lineWidth(0.7).strokeColor(COLORS.rule);
  pairs.forEach((p) => {
    doc.rect(x, y, colW, rowH).stroke();
    cellText(doc, (p.label || '').toUpperCase(), x, y, colW, rowH, {
      font: 'Helvetica-Bold', size: 7.5, color: COLORS.navy, align: 'left', padX: 4,
    });
    x += colW;

    doc.rect(x, y, colW, rowH).stroke();
    cellText(doc, p.value != null ? p.value : '-', x, y, colW, rowH, {
      font: 'Helvetica-Bold', size: 8.5, color: COLORS.gold,
    });
    x += colW;
  });
  doc.restore();

  return y + rowH;
}

// ---------------------------------------------------------------------------
// Section: key to terms used legend — laid out as a clean grid so labels
// never run into each other or off the page edge.
// ---------------------------------------------------------------------------
function drawKeyTerms(doc, ctx, startY, plan) {
  const { keyTerms } = ctx;
  let y = startY;

  doc.font('Helvetica-Bold').fontSize(8.5).fillColor('#b3261e')
    .text('Key to Terms Used:', MARGIN, y, { width: CONTENT_WIDTH, height: plan.keyTermsLabelH, ellipsis: true });
  y += plan.keyTermsLabelH;

  if (!keyTerms.length) return y;

  const rowH = plan.keyTermsRowH;
  const perItemW = Math.max(70, CONTENT_WIDTH / keyTerms.length);

  doc.save().lineWidth(0.6).strokeColor(COLORS.rule).rect(MARGIN, y, CONTENT_WIDTH, rowH).stroke().restore();

  let x = MARGIN;
  keyTerms.forEach((kt) => {
    const codeW = 24;
    cellText(doc, kt.code, x, y, codeW, rowH, {
      font: 'Helvetica-Bold', size: 7.5, color: COLORS.navy, align: 'left', padX: 4,
    });
    cellText(doc, kt.label, x + codeW, y, perItemW - codeW - 4, rowH, {
      font: 'Helvetica', size: 7.5, color: COLORS.ink, align: 'left', padX: 0,
    });
    x += perItemW;
  });

  return y + rowH;
}

// ---------------------------------------------------------------------------
// Section: result definitions table
// ---------------------------------------------------------------------------
function drawResultDefinitions(doc, ctx, startY, plan) {
  const { resultDefinitions } = ctx;
  if (!resultDefinitions.length) return startY;

  const labelW = 60;
  const rowH = plan.resultDefRowH;
  let y = startY;

  resultDefinitions.forEach((rd) => {
    doc.save().lineWidth(0.5).strokeColor(COLORS.ruleLight).rect(MARGIN, y, CONTENT_WIDTH, rowH).stroke();
    doc.moveTo(MARGIN + labelW, y).lineTo(MARGIN + labelW, y + rowH).stroke();
    doc.restore();
    cellText(doc, rd.label || '', MARGIN, y, labelW, rowH, {
      font: 'Helvetica-Bold', size: 7.5, color: '#b3261e', align: 'left', padX: 4,
    });
    cellText(doc, rd.text || '', MARGIN + labelW, y, CONTENT_WIDTH - labelW, rowH, {
      font: 'Helvetica', size: 7, color: COLORS.ink, align: 'left', padX: 6,
    });
    y += rowH;
  });

  return y;
}

// ---------------------------------------------------------------------------
// Section: class teacher's / headteacher's comment (label-above style)
// ---------------------------------------------------------------------------
function drawCompetencyComments(doc, ctx, startY, plan) {
  const { student } = ctx;
  let y = startY;

  const block = (label, text) => {
    doc.font('Helvetica-Bold').fontSize(8.5).fillColor(COLORS.ink)
      .text(label, MARGIN, y, { width: CONTENT_WIDTH, height: plan.commentLabelH, ellipsis: true });
    y += plan.commentLabelH;
    doc.save().lineWidth(0.6).strokeColor(COLORS.ruleLight).rect(MARGIN, y, CONTENT_WIDTH, plan.commentBoxH).stroke().restore();
    doc.font('Helvetica-Oblique').fontSize(8).fillColor('#2c4a8c')
      .text(text || '-', MARGIN + 6, y + 4, {
        width: CONTENT_WIDTH - 12, height: plan.commentBoxH - 8, ellipsis: true,
      });
    y += plan.commentBoxH + plan.GAP;
  };

  block("Class Teacher's Comment:", student.classTeacherComment);
  block("Headteacher's Comment:", student.headTeacherComment);

  return y - plan.GAP;
}

// ---------------------------------------------------------------------------
// Section: dates / fees footer row (values row + labels row)
// ---------------------------------------------------------------------------
function drawDatesFooterRow(doc, ctx, startY, plan) {
  const { student } = ctx;
  const fields = Array.isArray(student.footerFields) ? student.footerFields : [];
  if (!fields.length) return startY;

  const colW = CONTENT_WIDTH / fields.length;
  const rowH = plan.footerH / 2;
  let y = startY;

  doc.save().lineWidth(0.6).strokeColor(COLORS.rule);
  let x = MARGIN;
  fields.forEach((f) => {
    doc.rect(x, y, colW, rowH).stroke();
    cellText(doc, f.value || '', x, y, colW, rowH, { font: 'Helvetica', size: 8, color: COLORS.ink });
    x += colW;
  });
  y += rowH;

  x = MARGIN;
  fields.forEach((f) => {
    doc.rect(x, y, colW, rowH).fillAndStroke('#eef1f6', COLORS.rule);
    cellText(doc, (f.label || '').toUpperCase(), x, y, colW, rowH, { font: 'Helvetica-Bold', size: 6.5, color: COLORS.navy });
    x += colW;
  });
  doc.restore();
  y += rowH;

  return y;
}

module.exports = { buildCompetencyReportCardsPdf };