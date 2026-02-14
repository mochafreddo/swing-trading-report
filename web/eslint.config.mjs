import nextConfig from "eslint-config-next";
import nextTypeScriptConfig from "eslint-config-next/typescript";

const config = [...nextConfig, ...nextTypeScriptConfig];

export default config;
