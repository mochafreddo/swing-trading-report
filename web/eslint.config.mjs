import nextConfig from "eslint-config-next";
import nextTypeScriptConfig from "eslint-config-next/typescript";

const config = [
  { ignores: ["coverage/**"] },
  ...nextConfig,
  ...nextTypeScriptConfig,
];

export default config;
