import { gql } from '@apollo/client';

export const HEALTH = gql`
  query GatewayHealth {
    health {
      status
      version
    }
  }
`;
