import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /**
   * Emit a self-contained server bundle with a pruned dependency tree.
   *
   * Required by apps/web/Dockerfile, which copies only `.next/standalone` into the
   * runtime stage. Without this, the runtime image would need the full node_modules,
   * and with it the devDependencies (TypeScript, ESLint) would ship in production.
   */
  output: "standalone",

  // Do not advertise the framework and runtime version. The header gives an unauthenticated
  // caller a precise target inventory for no benefit, and docs/06 section 7 requires the
  // response surface to avoid disclosing implementation detail.
  poweredByHeader: false,
};

export default nextConfig;
