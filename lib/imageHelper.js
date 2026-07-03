const axios = require('axios');
const sharp = require('sharp');

/**
 * Downloads an image from a URL and resizes/normalizes it into a clean
 * PNG buffer suitable for embedding in the PDF, so that report cards stay
 * visually consistent regardless of the original image's size or format.
 *
 * @param {string} url
 * @param {{width:number, height:number, fit?:string}} opts
 * @returns {Promise<Buffer|null>} resized PNG buffer, or null if it could not be fetched
 */
async function fetchAndResizeImage(url, opts) {
  if (!url || typeof url !== 'string') return null;
  const { width, height, fit = 'cover' } = opts;

  try {
    const response = await axios.get(url, {
      responseType: 'arraybuffer',
      timeout: 10000,
      maxContentLength: 15 * 1024 * 1024, // 15MB safety cap
      headers: { 'User-Agent': 'report-card-api/1.0' },
    });

    const buffer = await sharp(response.data)
      .rotate() // respect EXIF orientation
      .resize(width, height, { fit, position: 'top' })
      .flatten({ background: '#ffffff' }) // remove transparency -> clean white background
      .png()
      .toBuffer();

    return buffer;
  } catch (err) {
    console.warn(`Image fetch/resize failed for ${url}: ${err.message}`);
    return null;
  }
}

module.exports = { fetchAndResizeImage };
