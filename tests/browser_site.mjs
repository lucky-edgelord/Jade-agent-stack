// Drive a deployed site in Chromium: the waitlist form saves, the records list shows rows, sign-up works.
// node tests/browser_site.mjs <site url>   (Playwright from $PLAYWRIGHT_DIR or ../jade-agent-ui-ux/node_modules)
import path from 'node:path';
const dir = process.env.PLAYWRIGHT_DIR || path.resolve(new URL('.', import.meta.url).pathname, '../../jade-agent-ui-ux/node_modules/playwright');
const { chromium } = await import(path.join(dir, 'index.mjs'));
const url = process.argv[2];
const b = await chromium.launch(); const p = await b.newPage();
const errors = []; p.on('pageerror', e => errors.push(e.message));
const out = {};
await p.goto(url + '/');
await p.getByLabel(/Email/).fill('grace@example.com');
await p.getByLabel(/Name/).fill('Grace');
await p.getByRole('button', { name: 'Join' }).click();
await p.getByText('You are on the list').waitFor({ timeout: 10000 });
out.form = true;
await p.getByLabel(/Email/).fill('not-an-email');
out.native_validation = await p.getByLabel(/Email/).evaluate(e => !e.checkValidity());
try { await p.locator('.records .rec').first().waitFor({ timeout: 10000 }); } catch (e) { console.error('records:', await p.locator('.records').innerText()); throw e; }
out.records = await p.locator('.records .rec h3').allInnerTexts();
await p.goto(url + '/account/');
const a = p.locator('jade-auth');
await a.getByRole('tab', { name: 'Create account' }).click();
await a.getByLabel('Email').fill('ada@example.com');
await a.getByLabel('Password', { exact: true }).fill('correct-horse-9');
const pc = a.getByLabel(/Confirm/); if (await pc.count()) await pc.fill('correct-horse-9');
await a.getByRole('button', { name: /Create account/ }).click();
await p.waitForURL(u => !u.pathname.startsWith('/account'), { timeout: 10000 });
out.signed_up_and_redirected = new URL(p.url()).pathname;
out.errors = errors;
console.log(JSON.stringify(out));
await b.close();
