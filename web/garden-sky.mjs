/** Privacy-safe sky selection. Geolocation is called only by explicit opt-in. */

export function quantizeRoughLocation(latitude, longitude) {
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || latitude < -90 || latitude > 90) {
    throw new Error('invalid sky location');
  }
  const normalized = ((longitude + 180) % 360 + 360) % 360 - 180;
  return Object.freeze({
    latitude_cell: Math.max(-90, Math.min(90, Math.round(latitude))),
    longitude_cell: Math.round(normalized) === 180 ? -180 : Math.round(normalized),
    grid_degrees: 1,
  });
}

export function resolveBrowserSky({ scene = {}, readerRegion = null } = {}) {
  const requested = scene.sky_mode ?? 'storybook_fallback';
  if (requested === 'reader_live' && readerRegion) {
    return { mode: 'reader_live', label: 'your local sky', region: readerRegion, astronomical: true };
  }
  if (['author_fixed', 'author_clock', 'story_event'].includes(requested) && scene.author_region) {
    return { mode: requested, label: 'authored story sky', region: scene.author_region, astronomical: true };
  }
  return { mode: 'storybook_fallback', label: 'storybook sky', region: null, astronomical: false };
}

export function greenwichApparentSiderealTime(unixSeconds) {
  const jd = Number(unixSeconds) / 86400 + 2440587.5;
  const jd0 = Math.floor(jd - 0.5) + 0.5;
  const hours = (jd - jd0) * 24;
  const dtt = jd - 2451545.0, dut = jd0 - 2451545.0, t = dtt / 36525;
  const gmst = (6.697375 + 0.065709824279 * dut + 1.0027379 * hours + 0.0000258 * t * t) % 24;
  const omega = (125.04 - 0.052954 * dtt) * Math.PI / 180;
  const sun = (280.47 + 0.98565 * dtt) * Math.PI / 180;
  const obliquity = (23.4393 - 0.0000004 * dtt) * Math.PI / 180;
  const equation = (-0.000319 * Math.sin(omega) - 0.000024 * Math.sin(2 * sun)) * Math.cos(obliquity);
  return ((gmst + equation) % 24 + 24) % 24;
}

export function altAz({ gastHours, raHours, decDegrees, latitude, longitude }) {
  const radians = value => value * Math.PI / 180;
  const degrees = value => value * 180 / Math.PI;
  const lha = radians((gastHours - raHours) * 15 + longitude);
  const dec = radians(decDegrees), lat = radians(latitude);
  const sinAltitude = Math.cos(lha) * Math.cos(dec) * Math.cos(lat) + Math.sin(dec) * Math.sin(lat);
  const altitude = degrees(Math.asin(Math.max(-1, Math.min(1, sinAltitude))));
  const azimuth = (degrees(Math.atan2(-Math.sin(lha), Math.tan(dec) * Math.cos(lat) - Math.sin(lat) * Math.cos(lha))) + 360) % 360;
  return [altitude, azimuth];
}

const BRIGHT_STARS = Object.freeze([
  ['sirius', 6.75247222, -16.71611111, -1.46], ['canopus', 6.3992, -52.6957, -0.74],
  ['arcturus', 14.261, 19.1825, -0.05], ['vega', 18.61563889, 38.78361111, 0.03],
  ['capella', 5.2782, 45.998, 0.08], ['rigel', 5.2423, -8.2016, 0.13],
  ['procyon', 7.655033, 5.225, 0.34], ['achernar', 1.6286, -57.2368, 0.46],
  ['betelgeuse', 5.919529, 7.4071, 0.50], ['hadar', 14.0637, -60.373, 0.61],
  ['altair', 19.846389, 8.868322, 0.76], ['acrux', 12.4433, -63.099, 0.76],
]);

export function projectSkyPoints(sky, unixSeconds, viewport) {
  if (!sky.astronomical || !sky.region) {
    return [[Math.floor(viewport[0] * 0.18), 1, '.'], [Math.floor(viewport[0] * 0.52), 2, '*'], [Math.floor(viewport[0] * 0.82), 1, '.']];
  }
  const gast = greenwichApparentSiderealTime(unixSeconds);
  return BRIGHT_STARS.map(([id, raHours, decDegrees, magnitude]) => {
    const [altitude, azimuth] = altAz({ gastHours: gast, raHours, decDegrees,
      latitude: sky.region.latitude_cell, longitude: sky.region.longitude_cell });
    return { id, altitude, azimuth, magnitude };
  }).filter(star => star.altitude >= 0).map(star => [
    Math.min(viewport[0] - 1, Math.floor((star.azimuth / 360) * viewport[0])),
    Math.max(0, Math.floor((1 - star.altitude / 90) * Math.max(1, viewport[1] * 0.55))),
    star.magnitude < 0.2 ? '*' : '.',
  ]);
}

export async function requestRoughSkyLocation({ geolocation = navigator.geolocation } = {}) {
  if (!geolocation) throw new Error('geolocation is unavailable');
  return new Promise((resolve, reject) => geolocation.getCurrentPosition(
    position => {
      const coarse = quantizeRoughLocation(position.coords.latitude, position.coords.longitude);
      // Raw position is never returned, logged, persisted, or transmitted.
      resolve(coarse);
    },
    () => reject(new Error('sky location was not shared')),
    { enableHighAccuracy: false, timeout: 5000, maximumAge: 3600000 },
  ));
}
