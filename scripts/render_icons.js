// Renders src/google_connections_mcp/icons/*.svg to PNG (256px, plus a 180px
// apple-touch-icon and the 16/32/48 sizes favicon.ico is built from).
// Run: NODE_PATH=$(npm root -g) node scripts/render_icons.js
// then: convert favicon-16.png favicon-32.png favicon-48.png favicon.ico (ImageMagick),
// which this script does itself when `convert` is on the PATH.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const dir = path.join(__dirname, '..', 'src', 'google_connections_mcp', 'icons');

async function render(page, svg, size, out) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(
    `<html><body style="margin:0;background:transparent">` +
    svg.replace(/width="256" height="256"/, `width="${size}" height="${size}"`) +
    `</body></html>`);
  await page.locator('svg').screenshot({ path: out, omitBackground: true });
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  for (const f of fs.readdirSync(dir).filter(f => f.endsWith('.svg'))) {
    const svg = fs.readFileSync(path.join(dir, f), 'utf8');
    await render(page, svg, 256, path.join(dir, f.replace(/\.svg$/, '.png')));
  }
  const general = fs.readFileSync(path.join(dir, 'google-connections.svg'), 'utf8');
  await render(page, general, 180, path.join(dir, 'apple-touch-icon.png'));
  const tmp = [];
  for (const s of [16, 32, 48]) {
    const out = path.join(dir, `favicon-${s}.png`);
    await render(page, general, s, out);
    tmp.push(out);
  }
  await browser.close();
  execFileSync('convert', [...tmp, path.join(dir, 'favicon.ico')]);
  tmp.forEach(f => fs.unlinkSync(f));
})();
