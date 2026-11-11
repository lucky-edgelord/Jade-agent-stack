// The demo site (demo: true) in Chromium with its pretend backend: models list, waitlist, sign-up, checkout, keys, reset.
// node tests/browser_demo.mjs <built site dir> <UI/UX dist dir>
import fs from 'node:fs'; import path from 'node:path';
const dir = process.env.PLAYWRIGHT_DIR || path.resolve(new URL('.', import.meta.url).pathname, '../../jade-agent-ui-ux/node_modules/playwright');
const { chromium } = await import(path.join(dir, 'index.mjs'));
const [site, dist] = process.argv.slice(2);
const b = await chromium.launch(); const ctx = await b.newContext(); const p = await ctx.newPage();
const errors = []; p.on('pageerror', e => errors.push(e.message));
await ctx.route('**/*', async r => {
  const u = new URL(r.request().url());
  if (u.hostname === 'cdn.jsdelivr.net' && u.pathname.includes('Jade-agent-ui-ux')) return r.fulfill({ path: path.join(dist, u.pathname.split('/dist/')[1]), contentType: 'text/javascript' });
  if (u.hostname === 'demo.test') { let f = path.join(site, u.pathname); if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, 'index.html'); return fs.existsSync(f) ? r.fulfill({ path: f }) : r.fulfill({ status: 404, body: '' }); }
  return r.abort();
});
const out = {};
const S = 'https://demo.test';
await p.goto(S + '/');
await p.getByText('a pretend backend runs in this browser').waitFor();
out.banner = true;
try { await p.locator('.records .rec').first().waitFor({ timeout: 8000 }); } catch (e) { console.error('records:', await p.locator('.records').innerText(), errors); throw e; }
out.models = await p.locator('.records .rec h3').allInnerTexts();
await p.getByLabel(/Email/).fill('ada@example.com');
await p.getByRole('button', { name: 'Join the waitlist' }).click();
await p.getByText("You're on the list").waitFor();
out.waitlist = true;
await p.getByRole('button', { name: 'What is this site?' }).click();
await p.getByText('The backend is pretend').waitFor();
out.chat = true;
// sign up on the account page
await p.goto(S + '/account/');
const A = p.locator('jade-auth').first();
await A.getByRole('tab', { name: 'Create account' }).click();
await A.getByLabel('Email').fill('ada@example.com');
await A.getByLabel('Password', { exact: true }).fill('correct-horse-9');
const pc = A.getByLabel(/Confirm/); if (await pc.count()) await pc.fill('correct-horse-9');
await A.getByRole('button', { name: /Create account/ }).click();
const C = p.locator('jade-account');
await C.getByText(/Free/i).first().waitFor();
out.account_free = true;
// subscribe to pro (simulated checkout)
await p.goto(S + '/pricing/');
const P = p.locator('jade-pricing');
await P.getByRole('button', { name: 'Choose pro' }).click();
try { await p.waitForURL(/billing=success/, { timeout: 8000 }); } catch (e) { console.error('pricing at:', p.url(), errors, await p.evaluate(() => Object.keys(localStorage))); throw e; }
await p.goto(S + '/account/');
await C.getByText(/Pro/).first().waitFor();
out.account_pro = true;
await C.getByLabel('New API key').fill('laptop');
await C.getByRole('button', { name: 'Create key' }).click();
await C.locator('[part=new-key]').waitFor();
out.key = (await C.locator('[part=new-key]').textContent()).startsWith('jab_');
await p.getByRole('button', { name: 'Reset demo' }).click();
await p.waitForLoadState();
await p.waitForTimeout(500);
out.reset = await p.evaluate(() => !localStorage.getItem('jade-base:https://demo.jade.invalid') && JSON.parse(localStorage.getItem('jade-demo:nimbus-ai')).users.length === 0);
out.errors = errors;
console.log(JSON.stringify(out));
await b.close();
