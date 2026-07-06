function dataUrlToBuffer(dataUrl) {
  if (!dataUrl) return null;
  const match = /^data:image\/(png|jpe?g);base64,(.+)$/i.exec(dataUrl);
  if (!match) return null;
  return Buffer.from(match[2], 'base64');
}

/** Formats an ISO date ("2010-04-20") as DD.MM.YYYY for display. Falls back to the raw string if it doesn't parse. */
function formatDate(input) {
  if (!input) return '';
  const d = new Date(input);
  if (Number.isNaN(d.getTime())) return String(input);
  const dd = String(d.getUTCDate()).padStart(2, '0');
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
  const yyyy = d.getUTCFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

module.exports = { dataUrlToBuffer, formatDate };
