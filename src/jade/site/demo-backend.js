/* Jade demo backend: a pretend Jade Agent Base that lives in this browser tab (localStorage), so a site with
   `demo: true` works with no server: sign-up and sign-in, plans and a simulated checkout, account usage and API keys,
   forms that save, and record lists. Nothing leaves the browser and no payment is taken.
   It answers fetch() calls to DEMO_URL in the shapes Jade Agent Base uses. */
(function () {
  var CFG = window.JADE_DEMO || {};
  var URL0 = CFG.url || 'https://demo.jade.invalid';
  var KEY = 'jade-demo:' + (CFG.site || 'site');
  var realFetch = window.fetch.bind(window);
  var rid = function (n) { var s = '', c = 'abcdefghijklmnopqrstuvwxyz0123456789'; for (var i = 0; i < (n || 15); i++) s += c[Math.floor(Math.random() * c.length)]; return s; };
  var now = function () { return new Date().toISOString().replace('T', ' ').replace(/\.\d+Z$/, '.000Z'); };
  function seed() {
    var db = { users: [], keys: [], records: {}, usage: {}, plans: [] };
    (CFG.plans || []).forEach(function (p, i) {
      db.plans.push({ id: 'plan' + i, collectionName: 'plans', name: p.name, description: p.description || '', price_month: p.price_month || 0, monthly_tokens: p.monthly_tokens || 0,
        monthly_budget: p.monthly_budget || 0, rpm: p.rpm || 0, default: !!p.default, active: p.active !== false, stripe_price: p.price_month ? 'price_demo_' + p.name : '' });
    });
    (CFG.collections || []).forEach(function (c) { db.records[c.name] = (c.records || []).map(function (r) { return Object.assign({ id: rid(), collectionName: c.name, created: now() }, r); }); });
    return db;
  }
  function load() { try { var d = JSON.parse(localStorage.getItem(KEY)); if (d && d.v === 1) return d; } catch (e) {} var s = seed(); s.v = 1; return s; }
  var db = load();
  function save() { try { localStorage.setItem(KEY, JSON.stringify(db)); } catch (e) {} }
  save();
  function res(status, body, headers) {
    return Promise.resolve(new Response(status === 204 ? null : JSON.stringify(body), { status: status, headers: Object.assign({ 'Content-Type': 'application/json' }, headers || {}) }));
  }
  function err(status, message, fields) {
    var data = {}; Object.keys(fields || {}).forEach(function (k) { data[k] = { code: 'validation_invalid', message: fields[k] }; });
    return res(status, { status: status, message: message, data: data });
  }
  function list(items) { return res(200, { items: items, page: 1, perPage: items.length, totalItems: items.length, totalPages: 1 }); }
  function pub(u) { return { id: u.id, collectionId: '_pb_users_auth_', collectionName: 'users', email: u.email, name: u.name || '', avatar: '', verified: true, plan: u.plan || '',
    subscription_status: u.plan ? 'active' : '', current_period_end: u.plan ? new Date(Date.now() + 30 * 864e5).toISOString() : '', created: u.created, updated: u.created }; }
  // tokens look like PocketBase's (a JWT with an expiry), so the UI keeps them; the signature is just "demo"
  var b64 = function (o) { return btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_'); };
  function tokenFor(u) { return b64({ alg: 'none', typ: 'JWT' }) + '.' + b64({ id: u.id, type: 'auth', collectionId: '_pb_users_auth_', exp: Math.floor(Date.now() / 1000) + 30 * 86400 }) + '.demo'; }
  function who(h) {
    var a = (h.get('Authorization') || '').replace(/^Bearer\s+/i, '');
    if (/\.demo$/.test(a)) { try { var id = JSON.parse(atob(a.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).id; return db.users.find(function (u) { return u.id === id; }) || null; } catch (e) { return null; } }
    if (a.indexOf('jab_') === 0) { var k = db.keys.find(function (k) { return k.key === a && !k.revoked; }); return k ? db.users.find(function (u) { return u.id === k.user; }) : null; }
    return null;
  }
  function planOf(u) { return db.plans.find(function (p) { return p.name === (u && u.plan); }) || db.plans.find(function (p) { return p.default; }) || { name: 'free', monthly_tokens: 0, monthly_budget: 0, rpm: 0 }; }
  function rule(col, op) { var c = (CFG.collections || []).find(function (x) { return x.name === col; }); return c ? c[op] : undefined; }
  function allowed(r, u, rec) {
    if (r === 'anyone' || r === '') return true;
    if (r === 'users') return !!u;
    if (r === 'owner') return !!u && (!rec || rec.user === u.id);
    return false; // admin, or nothing said
  }
  function handle(url, init) {
    var u = new URL(url), p = u.pathname, m = (init.method || 'GET').toUpperCase(), h = new Headers(init.headers || {});
    var body = {}; try { body = init.body ? JSON.parse(init.body) : {}; } catch (e) {}
    var me = who(h);
    if (p === '/api/health') return res(200, { message: 'API is healthy (demo).' });
    if (p === '/api/collections/users/auth-methods') return res(200, { password: { enabled: true, identityFields: ['email'] }, oauth2: { enabled: false, providers: [] }, mfa: { enabled: false }, otp: { enabled: false } });
    if (p === '/api/collections/users/records' && m === 'POST') {
      var f = {};
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(body.email || '')) f.email = 'Must be a valid email address.';
      else if (db.users.some(function (x) { return x.email === body.email; })) f.email = 'Value must be unique.';
      if ((body.password || '').length < 8) f.password = 'Must be at least 8 character(s).';
      if (body.passwordConfirm !== undefined && body.passwordConfirm !== body.password) f.passwordConfirm = "Values don't match.";
      if (Object.keys(f).length) return err(400, 'Failed to create record.', f);
      var nu = { id: rid(), email: body.email, password: body.password, name: body.name || '', plan: '', created: now() }; db.users.push(nu); save();
      return res(200, pub(nu));
    }
    if (p === '/api/collections/users/auth-with-password') {
      var x = db.users.find(function (y) { return y.email === body.identity && y.password === body.password; });
      return x ? res(200, { token: tokenFor(x), record: pub(x) }) : err(400, 'Failed to authenticate.');
    }
    if (p === '/api/collections/users/auth-refresh') return me ? res(200, { token: tokenFor(me), record: pub(me) }) : err(401, 'The request requires valid record authorization token.');
    if (p === '/api/collections/users/request-password-reset') return res(204);
    if (p === '/api/collections/plans/records') return list(db.plans.filter(function (x) { return x.active; }).sort(function (a, b) { return a.price_month - b.price_month; }));
    if (p === '/api/gateway/me') {
      if (!me) return err(401, 'Sign in or use an API key.');
      var pl = planOf(me), use = db.usage[me.id] || { tokens: 0, cost: 0 };
      return res(200, { user: me.id, plan: { name: pl.name, monthly_tokens: pl.monthly_tokens, monthly_budget: pl.monthly_budget, rpm: pl.rpm }, month: use });
    }
    if (p === '/api/billing/me') return me ? res(200, { plan: me.plan || '', status: me.plan ? 'active' : '', current_period_end: pub(me).current_period_end, has_billing_account: !!me.plan }) : err(401, 'Sign in.');
    if (p === '/api/billing/checkout') {
      if (!me) return err(401, 'Sign in.');
      var plan = db.plans.find(function (x) { return x.name === body.plan && x.stripe_price; });
      if (!plan) return err(400, 'The ' + body.plan + ' plan is not for sale.');
      me.plan = plan.name; db.usage[me.id] = db.usage[me.id] || { tokens: 0, cost: 0 }; save();
      var back = new URL(location.href); back.searchParams.set('billing', 'success');
      notice('Demo checkout: you are now on ' + plan.name + '. No payment was taken.');
      return res(200, { url: back.toString() });
    }
    if (p === '/api/billing/portal') { if (!me) return err(401, 'Sign in.'); notice('Demo: this is where the Stripe customer portal would open.'); return res(200, { url: location.href }); }
    if (p === '/api/collections/api_keys/records') {
      if (!me) return err(401, 'Sign in.');
      return list(db.keys.filter(function (k) { return k.user === me.id && !k.revoked; }).map(function (k) { return { id: k.id, name: k.name, prefix: k.prefix, created: k.created, last_used: k.last_used || '', revoked: false, user: k.user }; }).reverse());
    }
    if (p === '/api/gateway/keys' && m === 'POST') {
      if (!me) return err(401, 'Sign in.');
      var key = 'jab_' + rid(40), k = { id: rid(), user: me.id, name: body.name || 'key', key: key, prefix: key.slice(0, 16), created: now() };
      db.keys.push(k); var us = db.usage[me.id] || (db.usage[me.id] = { tokens: 0, cost: 0 }); us.tokens += 1200; us.cost += 0.002; save();
      return res(200, { note: 'Keep the key now: it is not shown again. (Demo: it only works on this page.)', key: key, id: k.id, prefix: k.prefix, name: k.name });
    }
    var rv = p.match(/^\/api\/gateway\/keys\/([^/]+)\/revoke$/);
    if (rv) { var kk = db.keys.find(function (k) { return k.id === decodeURIComponent(rv[1]) && me && k.user === me.id; }); if (!kk) return err(404, 'No such key.'); kk.revoked = true; save(); return res(200, { revoked: kk.id }); }
    var cr = p.match(/^\/api\/collections\/([^/]+)\/records(?:\/([^/]+))?$/);
    if (cr && db.records[cr[1]]) {
      var col = cr[1], items = db.records[col];
      if (m === 'POST') {
        if (!allowed(rule(col, 'create'), me)) return err(403, 'Only admins can perform this action.');
        var spec = (CFG.collections || []).find(function (c) { return c.name === col; }) || {}, bad = {};
        (spec.fields || []).forEach(function (fd) {
          var v = body[fd.name];
          if (fd.required && (v === undefined || v === null || v === '' || v === false)) bad[fd.name] = 'Cannot be blank.';
          else if (fd.type === 'email' && v && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v)) bad[fd.name] = 'Must be a valid email address.';
        });
        if (Object.keys(bad).length) return err(400, 'Failed to create record.', bad);
        var rec = Object.assign({}, body, { id: rid(), collectionName: col, created: now() }); if (me) rec.user = me.id; items.push(rec); save();
        return res(200, rec);
      }
      if (!allowed(rule(col, cr[2] ? 'view' : 'list'), me)) return cr[2] ? err(404, 'The requested resource wasn\'t found.') : list([]);
      if (cr[2]) { var one = items.find(function (r) { return r.id === cr[2]; }); return one ? res(200, one) : err(404, 'The requested resource wasn\'t found.'); }
      var sort = u.searchParams.get('sort'), out = items.slice();
      if (sort) { var d = sort[0] === '-' ? -1 : 1, f2 = sort.replace(/^[-+]/, ''); out.sort(function (a, b) { return (a[f2] > b[f2] ? 1 : a[f2] < b[f2] ? -1 : 0) * d; }); }
      var per = +u.searchParams.get('perPage') || 30;
      return list(out.slice(0, per));
    }
    return err(404, 'The demo backend has no ' + m + ' ' + p + '.');
  }
  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : input instanceof URL ? input.href : input && input.url;
    if (url && url.indexOf(URL0) === 0) {
      init = init || {};
      if (input instanceof Request) init = Object.assign({ method: input.method, headers: input.headers }, init);
      return new Promise(function (ok) { setTimeout(ok, 120 + Math.random() * 180); }).then(function () { return handle(url, init); });
    }
    return realFetch(input, init);
  };
  function notice(text) {
    var n = document.createElement('div'); n.setAttribute('role', 'status'); n.textContent = text;
    n.style.cssText = 'position:fixed;left:50%;bottom:64px;transform:translateX(-50%);background:var(--jade-fg,#111);color:var(--jade-bg,#fff);padding:10px 16px;border-radius:10px;z-index:2147483646;font:14px system-ui;box-shadow:0 8px 24px rgb(0 0 0/.2);max-width:92vw';
    (document.body || document.documentElement).appendChild(n); setTimeout(function () { n.remove(); }, 4500);
  }
  window.JadeDemo = { reset: function () { localStorage.removeItem(KEY); Object.keys(localStorage).filter(function (k) { return k.indexOf('jade-base:') === 0; }).forEach(function (k) { localStorage.removeItem(k); }); location.reload(); }, db: function () { return db; } };
  document.addEventListener('DOMContentLoaded', function () {
    var bar = document.createElement('div'); bar.className = 'jade-demo-bar';
    bar.innerHTML = '<span><b>Demo</b>: a pretend backend runs in this browser. Sign up with any email; nothing is sent anywhere and no payment is taken.</span> <button type="button">Reset demo</button>';
    bar.style.cssText = 'position:sticky;top:0;z-index:30;display:flex;gap:12px;align-items:center;justify-content:center;flex-wrap:wrap;padding:7px 14px;font:13px/1.4 system-ui;background:color-mix(in srgb,var(--jade-accent,#0b7a5b) 14%,var(--jade-bg,#fff));color:var(--jade-fg,#111);border-bottom:1px solid var(--jade-border,#ddd)';
    var b = bar.querySelector('button'); b.style.cssText = 'font:inherit;padding:3px 10px;border-radius:7px;border:1px solid var(--jade-border,#ccc);background:var(--jade-bg,#fff);color:inherit;cursor:pointer';
    b.onclick = window.JadeDemo.reset;
    document.body.insertBefore(bar, document.body.firstChild);
  });
})();
