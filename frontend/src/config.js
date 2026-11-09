export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true';

export const GATEWAY_URI =
  import.meta.env.VITE_GATEWAY_URI || '/graphql/';
