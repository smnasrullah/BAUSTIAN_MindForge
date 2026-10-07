// Chunk grouping for the production build (see vite.config.ts).
//
// Default splitting made ~70 sub-2 KB chunks (one per icon or shared helper) that a cold visit to
// a signed-in page fetched after the shell, six at a time over HTTP/1.1: ~7 s on Slow 4G
// (docs/PERFORMANCE.md). Code needed by the first load (the entry, landing and auth pages) keeps
// the default splitting so the first-load JS budget holds; everything else is grouped: route code
// and libraries shared by two or more routes, and icons.
import type { Plugin } from "vite";

const PUBLIC_ROOTS = /[\\/]src[\\/]features[\\/](landing|auth)[\\/]/;
const LUCIDE = /node_modules[\\/]lucide-react[\\/]/;
const LUCIDE_IMPORT = /import\s*\{([^}]*)\}\s*from\s*["']lucide-react["']/g;
const LUCIDE_EXPORT = /export\s*\{([^}]*)\}\s*from\s*["']\.\/icons\/([^"']+)["']/g;

interface Graph {
  modules: Set<string>;
  icons: Set<string>;
}
const entry: Graph = { modules: new Set(), icons: new Set() };
const publicPages: Graph = { modules: new Set(), icons: new Set() };

/** Records the static import graph of the entry and of the public pages at buildEnd. */
export function firstLoadGraph(): Plugin {
  return {
    name: "agentpulse-first-load-graph",
    apply: "build",
    buildEnd() {
      const ids = [...this.getModuleIds()];
      const iconFile = new Map<string, string>();
      const barrel = ids.find((id) => LUCIDE.test(id) && /lucide-react\.m?js$/.test(id));
      for (const m of (barrel ? (this.getModuleInfo(barrel)?.code ?? "") : "").matchAll(LUCIDE_EXPORT)) {
        for (const name of m[1].split(",")) iconFile.set(name.replace(/^\s*default\s+as\s+/, "").trim(), m[2]);
      }
      const walk = (roots: string[], g: Graph, skip: Set<string>) => {
        g.modules.clear();
        g.icons.clear();
        const stack = [...roots];
        while (stack.length > 0) {
          const id = stack.pop() as string;
          if (g.modules.has(id) || skip.has(id) || LUCIDE.test(id)) continue;
          g.modules.add(id);
          const info = this.getModuleInfo(id);
          for (const m of (info?.code ?? "").matchAll(LUCIDE_IMPORT)) {
            for (const name of m[1].split(",")) {
              const file = iconFile.get(name.trim().split(/\s+as\s+/)[0]);
              if (file) g.icons.add(file);
            }
          }
          stack.push(...(info?.importedIds ?? []));
        }
      };
      walk(ids.filter((id) => this.getModuleInfo(id)?.isEntry), entry, new Set());
      walk(ids.filter((id) => PUBLIC_ROOTS.test(id)), publicPages, entry.modules);
    },
  };
}

const iconOf = (id: string) => (LUCIDE.test(id) && /[\\/]icons[\\/]/.test(id) ? (id.split(/[\\/]/).pop() ?? "") : null);
const firstLoad = (id: string) => entry.modules.has(id) || publicPages.modules.has(id);

export const codeSplitting = {
  includeDependenciesRecursively: false,
  groups: [
    { name: "maplibre", test: /node_modules[\\/]maplibre-gl/, priority: 30 },
    {
      name: "icons-public",
      test: (id: string) => {
        const f = iconOf(id);
        return f !== null && publicPages.icons.has(f) && !entry.icons.has(f);
      },
      priority: 21,
    },
    {
      name: "icons",
      test: (id: string) => {
        const f = iconOf(id);
        return f !== null && !publicPages.icons.has(f) && !entry.icons.has(f);
      },
      priority: 20,
    },
    {
      name: "vendor-lazy",
      test: (id: string) => id.includes("node_modules") && !LUCIDE.test(id) && !firstLoad(id),
      priority: 15,
      minShareCount: 2,
    },
    {
      name: "shared",
      test: (id: string) => !id.includes("node_modules") && /[\\/]src[\\/]/.test(id) && !firstLoad(id),
      priority: 10,
      minShareCount: 2,
    },
  ],
};
