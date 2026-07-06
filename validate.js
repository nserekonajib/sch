const DATA_URL_RE = /^data:image\/(png|jpe?g);base64,/i;

function isNonEmptyString(v) {
  return typeof v === 'string' && v.trim().length > 0;
}

/**
 * Validates the incoming request body for POST /api/id-cards
 * Throws a ValidationError (with .status = 400) on any problem.
 */
class ValidationError extends Error {
  constructor(message) {
    super(message);
    this.status = 400;
    this.name = 'ValidationError';
  }
}

function requireImageField(obj, path, { required }) {
  const val = obj;
  if (val === undefined || val === null) {
    if (required) throw new ValidationError(`${path} is required`);
    return;
  }
  if (!isNonEmptyString(val)) {
    throw new ValidationError(`${path} must be a base64 data URL string`);
  }
  if (!DATA_URL_RE.test(val)) {
    throw new ValidationError(
      `${path} must be a base64 data URL, e.g. "data:image/png;base64,...."`
    );
  }
}

function validateRequest(body) {
  if (!body || typeof body !== 'object') {
    throw new ValidationError('Request body must be a JSON object');
  }

  const { branding, student, qrData, options } = body;

  // ---- branding ----
  if (!branding || typeof branding !== 'object') {
    throw new ValidationError('branding object is required');
  }
  if (!isNonEmptyString(branding.organizationName)) {
    throw new ValidationError('branding.organizationName is required');
  }
  requireImageField(branding.logoBase64, 'branding.logoBase64', { required: false });
  requireImageField(branding.sealBase64, 'branding.sealBase64', { required: false });

  if (branding.primaryColor && !isNonEmptyString(branding.primaryColor)) {
    throw new ValidationError('branding.primaryColor must be a string (hex color)');
  }
  if (branding.secondaryColor && !isNonEmptyString(branding.secondaryColor)) {
    throw new ValidationError('branding.secondaryColor must be a string (hex color)');
  }

  // ---- student ----
  if (!student || typeof student !== 'object') {
    throw new ValidationError('student object is required');
  }
  const requiredStudentFields = ['surname', 'firstName', 'studentId'];
  for (const f of requiredStudentFields) {
    if (!isNonEmptyString(student[f])) {
      throw new ValidationError(`student.${f} is required`);
    }
  }
  requireImageField(student.photoBase64, 'student.photoBase64', { required: true });
  requireImageField(student.signatureBase64, 'student.signatureBase64', { required: false });

  // ---- qrData ----
  if (qrData === undefined || qrData === null || qrData === '') {
    throw new ValidationError('qrData is required (string, or JSON object to be encoded)');
  }

  // ---- options ----
  if (options !== undefined) {
    if (typeof options !== 'object') {
      throw new ValidationError('options must be an object');
    }
    if (options.bleedMm !== undefined && typeof options.bleedMm !== 'number') {
      throw new ValidationError('options.bleedMm must be a number');
    }
    if (
      options.includeMrz !== undefined &&
      typeof options.includeMrz !== 'boolean'
    ) {
      throw new ValidationError('options.includeMrz must be a boolean');
    }
  }

  return true;
}

/**
 * Validates POST /api/id-cards/batch bodies of the shape:
 * { branding?, options?, cards: [ { student, qrData, branding?, options? }, ... ] }
 * Shared top-level `branding`/`options` act as defaults, merged with (and
 * overridden by) any per-card `branding`/`options`. Returns the array of
 * fully-merged, individually-valid card payloads.
 */
function validateBatchRequest(body) {
  if (!body || typeof body !== 'object') {
    throw new ValidationError('Request body must be a JSON object');
  }
  if (!Array.isArray(body.cards) || body.cards.length === 0) {
    throw new ValidationError('cards must be a non-empty array');
  }
  if (body.cards.length > 200) {
    throw new ValidationError('cards array too large (max 200 per request)');
  }

  const sharedBranding = body.branding && typeof body.branding === 'object' ? body.branding : {};
  const sharedOptions = body.options && typeof body.options === 'object' ? body.options : {};

  return body.cards.map((entry, i) => {
    if (!entry || typeof entry !== 'object') {
      throw new ValidationError(`cards[${i}] must be an object`);
    }
    const merged = {
      branding: { ...sharedBranding, ...(entry.branding || {}) },
      student: entry.student,
      qrData: entry.qrData,
      options: { ...sharedOptions, ...(entry.options || {}) },
    };
    try {
      validateRequest(merged);
    } catch (e) {
      throw new ValidationError(`cards[${i}]: ${e.message}`);
    }
    return merged;
  });
}

module.exports = { validateRequest, validateBatchRequest, ValidationError };
