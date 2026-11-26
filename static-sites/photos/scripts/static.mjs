import { copyFileSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import nunjucks from "nunjucks";

export const root = resolve(fileURLToPath(new URL("..", import.meta.url)));

const env = nunjucks.configure(join(root, "src"), {
  autoescape: true,
  noCache: true,
});

export function compilePages(dist) {
  const pages = join(root, "src/pages");
  mkdirSync(dist, { recursive: true });
  for (const name of readdirSync(pages)) {
    if (!name.endsWith(".njk")) {
      continue;
    }
    const html = env.render(`pages/${name}`);
    const dest = join(dist, name.replace(/\.njk$/, ".html"));
    writeFileSync(dest, html.endsWith("\n") ? html : `${html}\n`);
  }
}

export function copyAssets(dist) {
  mkdirSync(join(dist, "assets"), { recursive: true });
  copyFileSync(join(root, "cropped_final.jpg"), join(dist, "cropped_final.jpg"));
  copyFileSync(join(root, "src/styles.css"), join(dist, "assets/styles.css"));
}
