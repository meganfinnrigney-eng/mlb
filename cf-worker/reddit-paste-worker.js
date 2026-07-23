/**
 * Cloudflare Worker: secure write-proxy for docs/paste.html.
 *
 * Why a Worker at all, instead of having the page call GitHub's API
 * directly: GitHub Pages is 100% static, so any secret embedded in
 * docs/paste.html's client-side JS would be visible to literally anyone
 * who loads the page (view-source, devtools, or just re-requesting the
 * JS file) - unacceptable once this repo is public, no matter how the
 * password check is dressed up. A Worker is the smallest "hold a real
 * secret server-side" primitive that still fits a static-site project:
 * no server to run or pay for, secrets are encrypted and only ever
 * injected into the Worker's own execution, never sent to the browser.
 *
 * Why this instead of repository_dispatch + a GitHub Action: dispatching
 * an Action is async (the page would have to poll a second endpoint to
 * find out if the commit actually happened) and still needs *something*
 * holding a real GitHub credential to make the dispatch call in the
 * first place - so it doesn't remove the need for this Worker, it just
 * adds an extra hop. Calling the Contents API directly is simpler and
 * gives an immediate success/failure response to show on the page.
 *
 * Deploy (Cloudflare dashboard, no CLI needed):
 *   1. dash.cloudflare.com -> Workers & Pages -> Create -> Create Worker.
 *   2. Paste this file's contents into the editor, Deploy.
 *   3. Worker -> Settings -> Variables and Secrets -> add two, both
 *      type "Secret" (encrypted, never shown again after saving):
 *        PASTE_SECRET  - a password only you know; typed into
 *                        docs/paste.html's "Access code" field.
 *        GITHUB_TOKEN  - a GitHub fine-grained personal access token
 *                        (github.com/settings/personal-access-tokens/new),
 *                        scoped to ONLY this repository, with "Contents:
 *                        Read and write" permission and nothing else.
 *                        GitHub can't scope a token down to a single
 *                        subfolder, so this token can technically write
 *                        any file in the repo - the password gate below
 *                        is what actually stops that from being usable
 *                        by anyone but you. Rotate PASTE_SECRET (Worker
 *                        secrets update instantly, no redeploy) if you
 *                        ever suspect it leaked.
 *   4. Copy the Worker's *.workers.dev URL into docs/paste.html's
 *      WORKER_URL constant, commit, done.
 */

const OWNER = "meganfinnrigney-eng";
const REPO = "mlb";
const BRANCH = "main";
const ALLOWED_ORIGIN = "https://meganfinnrigney-eng.github.io";
const MAX_TEXT_LENGTH = 200000; // sanity cap, not a real rate limit

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
    },
  });
}

function timingSafeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function todayEasternISO() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
}

function isValidDate(s) {
  return typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s);
}

function utf8ToBase64(text) {
  return btoa(unescape(encodeURIComponent(text)));
}

async function ghFetch(env, path, options = {}) {
  return fetch(`https://api.github.com${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "mlb-daily-tracker-paste-worker",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(options.headers || {}),
    },
  });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
          "Access-Control-Allow-Methods": "POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    if (request.method !== "POST") {
      return jsonResponse({ ok: false, error: "method not allowed" }, 405);
    }

    if (!env.PASTE_SECRET || !env.GITHUB_TOKEN) {
      return jsonResponse({ ok: false, error: "worker not configured" }, 500);
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return jsonResponse({ ok: false, error: "invalid JSON" }, 400);
    }

    const { password, text, date } = body || {};

    if (!timingSafeEqual(password, env.PASTE_SECRET)) {
      return jsonResponse({ ok: false, error: "unauthorized" }, 401);
    }
    if (typeof text !== "string" || !text.trim()) {
      return jsonResponse({ ok: false, error: "no text provided" }, 400);
    }
    if (text.length > MAX_TEXT_LENGTH) {
      return jsonResponse({ ok: false, error: "text too long" }, 400);
    }

    const fileDate = isValidDate(date) ? date : todayEasternISO();
    const path = `mlb_daily/data/reddit_manual_${fileDate}.txt`;

    // Updating an existing file requires its current blob sha; a 404 just
    // means this is the first paste for that date (create, no sha needed).
    let sha;
    const existing = await ghFetch(env, `/repos/${OWNER}/${REPO}/contents/${path}?ref=${BRANCH}`);
    if (existing.status === 200) {
      sha = (await existing.json()).sha;
    } else if (existing.status !== 404) {
      return jsonResponse({ ok: false, error: `GitHub lookup failed (${existing.status})` }, 502);
    }

    const putRes = await ghFetch(env, `/repos/${OWNER}/${REPO}/contents/${path}`, {
      method: "PUT",
      body: JSON.stringify({
        message: `Manual Reddit paste for ${fileDate}`,
        content: utf8ToBase64(text),
        branch: BRANCH,
        ...(sha ? { sha } : {}),
      }),
    });

    if (!putRes.ok) {
      return jsonResponse({ ok: false, error: `GitHub write failed (${putRes.status})` }, 502);
    }

    return jsonResponse({ ok: true, date: fileDate });
  },
};
