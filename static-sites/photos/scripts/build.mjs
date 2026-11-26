import * as esbuild from "esbuild";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { compilePages, copyAssets, root } from "./static.mjs";

const dist = join(root, "dist");
mkdirSync(join(dist, "assets"), { recursive: true });

await esbuild.build({
  entryPoints: [join(root, "src/main.ts")],
  bundle: true,
  minify: true,
  outfile: join(dist, "assets/main.js"),
});

compilePages(dist);
copyAssets(dist);
