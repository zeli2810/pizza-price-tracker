// Vercel serverless function — triggers the Pais Plus scraper's GitHub Actions
// workflow via a repository_dispatch event, since the actual Playwright
// scraping can't run inside a Vercel function (needs a real browser + long
// execution time).
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') {
    res.status(204).end();
    return;
  }
  if (req.method !== 'POST') {
    res.status(405).json({ ok: false, error: 'Method not allowed' });
    return;
  }

  const token = process.env.GITHUB_TOKEN;
  const repo = process.env.GITHUB_REPO || 'zeli2810/pizza-price-tracker';
  if (!token) {
    res.status(500).json({ ok: false, error: 'GITHUB_TOKEN is not configured' });
    return;
  }

  try {
    const ghResp = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ event_type: 'manual-refresh-paisplus' }),
    });

    if (ghResp.status === 204) {
      res.status(200).json({ ok: true, message: 'Scrape started' });
    } else {
      const text = await ghResp.text();
      res.status(ghResp.status).json({ ok: false, error: text });
    }
  } catch (e) {
    res.status(500).json({ ok: false, error: String(e) });
  }
}
