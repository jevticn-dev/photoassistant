/**
 * A minimal PNG writer: 8-bit RGB, one IDAT, no interlacing.
 *
 * Written out rather than taken from a library, and the reasoning is narrower
 * than the one behind hand-writing the curve. There the point was that the
 * *algorithm* had to be provably the same on both sides; here it is only that
 * the golden test writes a few hundred files and a dependency for forty lines of
 * well-specified container format is not worth carrying. Correctness is
 * self-evident on the other end: Pillow reads these files, and the first thing
 * the golden test asserts is that a neutral recipe round-trips byte for byte.
 *
 * PNG is used rather than a raw dump because when the golden test fails the next
 * question is always what the difference *looks* like — and the lesson of phase
 * 1b, twice over, is that the picture says what the average does not.
 */

import { deflateSync, crc32 } from 'node:zlib';

const SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function chunk(type, body) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(body.length);

  const typed = Buffer.concat([Buffer.from(type, 'ascii'), body]);

  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(typed) >>> 0);

  return Buffer.concat([length, typed, checksum]);
}

/**
 * Encode RGBA bytes, row 0 first, as an 8-bit RGB PNG.
 *
 * The alpha channel is dropped: the renderer writes opaque pixels, and carrying
 * a constant channel into the comparison would only invite someone to compare it.
 */
export function encodePng(rgba, width, height) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8; // bit depth
  header[9] = 2; // colour type: truecolour, no alpha
  header[10] = 0; // deflate
  header[11] = 0; // adaptive filtering
  header[12] = 0; // no interlace

  // Filter type 0 on every row. Filtering exists to help compression, and these
  // are test images written a few hundred at a time — predictability is worth
  // more here than size.
  const stride = width * 3;
  const raw = Buffer.alloc(height * (stride + 1));
  for (let row = 0; row < height; row++) {
    const at = row * (stride + 1);
    raw[at] = 0;
    for (let column = 0; column < width; column++) {
      const source = (row * width + column) * 4;
      const target = at + 1 + column * 3;
      raw[target] = rgba[source];
      raw[target + 1] = rgba[source + 1];
      raw[target + 2] = rgba[source + 2];
    }
  }

  return Buffer.concat([
    SIGNATURE,
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}
