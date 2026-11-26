import next from "eslint-config-next";

const config = [
  ...next,
  { ignores: [".next/**", "node_modules/**", "public/**", "next-env.d.ts"] },
  {
    rules: {
      // Editable forms are hydrated once from server responses (React Query); this is intentional.
      "react-hooks/set-state-in-effect": "warn",
      // Hard navigations are deliberate after login/logout to drop all client state.
      "@next/next/no-location-assign-relative-destination": "off",
    },
  },
];

export default config;
