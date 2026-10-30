// Browser QA + documentation screenshots for SmartPark.
//
//   npm install puppeteer-core            (once, anywhere on your machine)
//   python manage.py seed_demo && python manage.py runserver
//   BASE=http://127.0.0.1:8000 OUT=docs/screenshots CHROME_PATH="/path/to/chrome" node tools/screenshots.mjs
//
// It logs in as the demo accounts, visits the main pages at desktop and phone width, saves screenshots, and reports
// anything a visitor's browser would complain about: console errors (including Content-Security-Policy violations),
// failed requests, HTTP errors and horizontal overflow. Exits with status 1 if it finds a problem.
import fs from 'fs';
import puppeteer from 'puppeteer-core';

const BASE = (process.env.BASE || 'http://127.0.0.1:8000').replace(/\/$/, '');
const OUT = process.env.OUT || 'docs/screenshots';
const CHROME_PATH = process.env.CHROME_PATH;
const CHROME_ARGS = (process.env.CHROME_ARGS || '--no-sandbox').split(' ').filter(Boolean);
const ADMIN = [process.env.ADMIN_USER || 'admin_demo', process.env.ADMIN_PASSWORD || 'DemoAdmin#2026'];
const USER = [process.env.DEMO_USER || 'user_demo', process.env.DEMO_PASSWORD || 'DemoUser#2026'];
if (!CHROME_PATH) { console.error('Set CHROME_PATH to a Chrome/Chromium executable.'); process.exit(2); }
fs.mkdirSync(OUT, {recursive: true});

const DESKTOP = [1366, 900], PHONE = [390, 844];
const problems = [];
const browser = await puppeteer.launch({executablePath: CHROME_PATH, args: CHROME_ARGS, headless: 'shell'});
const page = await browser.newPage();
const cdp = await page.createCDPSession();
const where = () => page.url().replace(BASE, '') || '/';
page.on('console', m => { if (['error', 'warning'].includes(m.type())) problems.push(`console.${m.type()} on ${where()}: ${m.text().slice(0, 200)}`); });
page.on('pageerror', e => problems.push(`script error on ${where()}: ${String(e).slice(0, 200)}`));
page.on('requestfailed', r => problems.push(`request failed: ${r.url().replace(BASE, '')} (${r.failure()?.errorText})`));
page.on('response', r => { if (r.status() >= 400) problems.push(`HTTP ${r.status()}: ${r.url().replace(BASE, '')}`); });

async function loginAs([username, password]) {
  await cdp.send('Network.clearBrowserCookies');
  await page.goto(BASE + '/accounts/login/', {waitUntil: 'networkidle0'});
  await page.type('#id_username', username);
  await page.type('#id_password', password);
  await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.click('.auth-panel button[type=submit]')]);
}

async function shot(path, name, [w, h] = DESKTOP, prepare) {
  await page.setViewport({width: w, height: h});
  await page.goto(BASE + path, {waitUntil: 'networkidle0'});
  if (prepare) await prepare();
  // Charts animate in; software-rendered headless browsers can stall that animation, so draw the final state.
  await page.evaluate(() => { if (typeof Chart !== 'undefined') Object.values(Chart.instances).forEach(c => { c.options.animation = false; c.update('none'); }); });
  await new Promise(r => setTimeout(r, 500));
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (overflow > 0) problems.push(`horizontal overflow of ${overflow}px on ${path} at ${w}px wide`);
  await page.screenshot({path: `${OUT}/${name}.png`, fullPage: true});
  console.log(`saved ${OUT}/${name}.png`);
}
const json = path => page.evaluate(async p => (await fetch(p)).json(), path);

await page.goto(BASE + '/', {waitUntil: 'networkidle0'});
const location = (await json('/api/parking/locations/?available=1')).results[0];
if (!location) { console.error('No parking locations: run `python manage.py seed_demo` first.'); process.exit(2); }
const slot = (await json(`/api/parking/slots/?location=${location.id}&status=available&slot_type=car`)).results[0];

await shot('/', 'home'); await shot('/', 'home-mobile', PHONE);
await shot('/parking/', 'parking'); await shot(`/parking/${location.id}/`, 'location');
await shot('/accounts/login/', 'login');

await loginAs(USER);
await shot('/bookings/', 'history');
const ref = await page.evaluate(() => document.querySelector('a[href^="/bookings/PK-"]')?.getAttribute('href'));
if (ref) await shot(ref, 'booking');
await shot(`/bookings/book/${slot.id}/`, 'book', DESKTOP, async () => {
  const at = hours => new Date(Date.now() + hours * 3600e3 - new Date().getTimezoneOffset() * 60e3).toISOString().slice(0, 16);
  await page.evaluate((a, b) => { for (const [id, v] of [['#id_start_time', a], ['#id_end_time', b]]) { const el = document.querySelector(id); el.value = v; el.dispatchEvent(new Event('change')); } }, at(30), at(32));
  await page.waitForFunction(() => /Estimated charge/.test(document.querySelector('#estimate')?.textContent || ''), {timeout: 5000}).catch(() => problems.push('fee estimate did not appear on the booking form'));
});

await loginAs(ADMIN);
let charts = [];
await shot('/dashboard/', 'dashboard', DESKTOP, async () => { charts = await page.evaluate(() => typeof Chart === 'undefined' ? [] : Object.keys(Chart.instances)); });
if (charts.length !== 5) problems.push(`expected 5 dashboard charts, found ${charts.length}`);
await shot('/dashboard/', 'dashboard-mobile', PHONE);

await browser.close();
console.log(problems.length ? `\n${problems.length} problem(s):\n - ${[...new Set(problems)].join('\n - ')}` : '\nNo console errors, CSP violations, failed requests, overflow or missing charts.');
process.exit(problems.length ? 1 : 0);
